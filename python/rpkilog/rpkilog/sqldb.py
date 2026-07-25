"""
Shared SQL-database CLI helpers: connection handling and startup-argument logging, used by the
reconcile and archive-site-crawler entry points.  Also home of the
rpkilog-database-security-group CLI, which maintains the AWS Security Group rules allowing
internet clients (SOHO networks, the rpkiclient linode, etc.) to reach the RDS database.

This module must stay dependency-light and must NOT import the CLI modules: reconcile.py imports
ArchiveSiteCrawler (for derive_tar_url()), and the crawler needs these helpers too, so hosting
them in either CLI module would create a circular import.
"""
import argparse
import ipaddress
import json
import logging
import os
import re

import boto3
import mariadb
import requests

from rpkilog.data_file_source import DataFileSource
from rpkilog.data_file_type import DataFileType

logger = logging.getLogger(__name__)

# The Security Group(s) this tool manages are found by both tag pairs below.  Groups tagged
# cli_managed=True contain exclusively CLI-managed rules; Terraform-managed rules live in a
# sibling group without that tag, so the two toolchains never fight over a rule.
SECURITY_GROUP_TAG_KEY = 'applies_to'
SECURITY_GROUP_TAG_VALUE = 'internet_database'
CLI_MANAGED_TAG_KEY = 'cli_managed'
CLI_MANAGED_TAG_VALUE = 'True'
# Each client's rules carry this tag so they can be replaced when the client's address changes
RULE_CLIENT_TAG_KEY = 'client'
CLIENT_TAG_VALUE_REGEX = r'[A-Za-z0-9_\-./]+'
DATABASE_PORT = 3306
# api.ipify.org has only A records and api6.ipify.org only AAAA, giving per-family discovery
IP_DISCOVERY_URLS = {
    4: 'https://api4.ipify.org',
    6: 'https://api6.ipify.org',
}


def db_connect(args: argparse.Namespace) -> mariadb.SyncConnection:
    """
    Connect to MariaDB using args.db_* and make the connection available to the SQL-row classes.

    The password comes from args.db_password, falling back to env RPKILOG_DB_PASSWORD.

    TODO: prod will use RDS IAM auth tokens instead of a static password

    TOTEST:
    - test_db_connect_password_falls_back_to_env: args.db_password unset + RPKILOG_DB_PASSWORD
      set connects using the env value (mariadb.connect monkeypatched)
    - test_db_connect_cli_password_beats_env: an explicit --db-password wins over the env var
    - test_db_connect_sets_default_db_connections: DataFileSource.default_db_connection and
      DataFileType.default_db_connection are the returned connection afterward
    """
    password = args.db_password
    if password is None:
        password = os.environ.get('RPKILOG_DB_PASSWORD')
    retval = mariadb.connect(
        host=args.db_host,
        port=args.db_port,
        user=args.db_user,
        password=password,
        database=args.db_name,
        autocommit=True,
    )
    DataFileSource.default_db_connection = retval
    DataFileType.default_db_connection = retval
    return retval


def log_startup_args(args: argparse.Namespace, secret_dests: set[str]):
    """
    Log the parsed CLI arguments at INFO except those in secret_dests
    """
    parts = []
    for dest in sorted(vars(args)):
        value = getattr(args, dest)
        if dest in secret_dests and value is not None:
            value_repr = "'<redacted>'"
        else:
            value_repr = repr(value)
        parts.append(f'{dest}={value_repr}')
    logger.info('invoked with args: ' + ' '.join(parts))


def client_tag_value(value: str) -> str:
    """
    Validate a client name for use as an AWS tag value: alphanumeric plus ``_-./``.  Used both as
    the argparse type for --client and by security_group_update() for programmatic callers; raises
    ValueError, which argparse renders as a clean usage error.

    TOTEST:
    - test_client_tag_value_accepts_typical: 'soho', 'rpkiclient-uploader', 'jsw/home.net' return
      unchanged
    - test_client_tag_value_rejects_bad: '', 'has space', 'bang!' raise ValueError
    """
    if not re.fullmatch(CLIENT_TAG_VALUE_REGEX, value):
        raise ValueError(f'invalid client value {value!r}: must match {CLIENT_TAG_VALUE_REGEX}')
    return value


def discover_client_cidrs(v4_subnet_length: int = 32, v6_subnet_length: int = 128) -> list[str]:
    """
    Discover this host's public IPv4 and IPv6 addresses via ipify and return them as CIDR strings.

    Each discovered address is widened to the given subnet length (e.g. v6_subnet_length=56 turns
    2001:db8:1:2::3 into 2001:db8:1::/56) so a whole SOHO delegation can be allowed at once.  A
    family that cannot be discovered (e.g. no IPv6 connectivity) is skipped with a warning; if
    neither family works, RuntimeError is raised.

    TOTEST:
    - test_discover_client_cidrs_both_families: requests.get monkeypatched to return an address
      per family; result is ['192.0.2.7/32', '2001:db8::7/128'] with default lengths
    - test_discover_client_cidrs_subnet_lengths: v4_subnet_length=24 / v6_subnet_length=56 widen
      to the containing network ('192.0.2.0/24', '2001:db8::/56')
    - test_discover_client_cidrs_one_family_down: one URL raising ConnectionError still returns
      the other family's CIDR
    - test_discover_client_cidrs_all_down: both URLs failing raises RuntimeError
    """
    retlist = []
    for ip_version in sorted(IP_DISCOVERY_URLS):
        url = IP_DISCOVERY_URLS[ip_version]
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            address = ipaddress.ip_address(response.text.strip())
        except Exception as ex:
            logger.warning(f'could not discover IPv{ip_version} address from {url}: {ex}')
            continue
        if address.version == 4:
            subnet_length = v4_subnet_length
        else:
            subnet_length = v6_subnet_length
        network = ipaddress.ip_network(f'{address}/{subnet_length}', strict=False)
        retlist.append(str(network))
    if len(retlist) == 0:
        raise RuntimeError('could not discover any public IP address; check connectivity or use --cidr')
    return retlist


def security_groups_find(ec2) -> list[dict]:
    """
    Return the Security Group(s) tagged applies_to=internet_database and cli_managed=True --
    the groups whose rules this tool manages; raise if none exist.
    """
    retlist = []
    paginator = ec2.get_paginator('describe_security_groups')
    filters = [
        {'Name': f'tag:{SECURITY_GROUP_TAG_KEY}', 'Values': [SECURITY_GROUP_TAG_VALUE]},
        {'Name': f'tag:{CLI_MANAGED_TAG_KEY}', 'Values': [CLI_MANAGED_TAG_VALUE]},
    ]
    for page in paginator.paginate(Filters=filters):
        for group in page['SecurityGroups']:
            retlist.append(group)
    if len(retlist) == 0:
        raise RuntimeError(
            f'no Security Groups found with tags {SECURITY_GROUP_TAG_KEY}={SECURITY_GROUP_TAG_VALUE} '
            f'and {CLI_MANAGED_TAG_KEY}={CLI_MANAGED_TAG_VALUE}'
        )
    return retlist


def security_group_rules_list(ec2, group_id: str) -> list[dict]:
    """
    Return all rules of the given Security Group.
    """
    retlist = []
    paginator = ec2.get_paginator('describe_security_group_rules')
    for page in paginator.paginate(Filters=[{'Name': 'group-id', 'Values': [group_id]}]):
        for rule in page['SecurityGroupRules']:
            retlist.append(rule)
    return retlist


def rule_tags_as_dict(rule: dict) -> dict:
    """
    Return a Security Group rule's Tags list as a {key: value} dict.

    TOTEST:
    - test_rule_tags_as_dict: [{'Key': 'client', 'Value': 'soho'}] becomes {'client': 'soho'};
      a rule without Tags becomes {}
    """
    retdict = {}
    for tag in rule.get('Tags', []):
        retdict[tag['Key']] = tag['Value']
    return retdict


def security_group_update(
        client: str,
        cidrs: list[str] | None = None,
        v4_subnet_length: int = 32,
        v6_subnet_length: int = 128,
        ec2=None,
) -> dict:
    """
    Ensure the CLI-managed Security Group(s) (tagged applies_to=internet_database and
    cli_managed=True) contain port-3306 ingress rules tagged client=<client> for the given (or
    discovered) CIDRs, removing any stale rules carrying that client tag.  Rules already matching
    a desired CIDR are left in place, so an unchanged client address is a no-op -- safe to run
    from cron.  Terraform-managed rules live in a sibling group without the cli_managed tag,
    which this tool never touches.

    Programmatic callers (e.g. rpkiclient_uploader keeping its own DB access current) may pass a
    boto3 ec2 client; cidrs=None discovers this host's public addresses via ipify.

    Returns {group_id: {'created': [cidr, ...], 'removed': [rule_id, ...]}}.

    TOTEST (ec2 stubbed via the DI param):
    - test_security_group_update_noop: existing tagged rule already matches the desired CIDR;
      no revoke/authorize calls are made
    - test_security_group_update_replaces_stale: a tagged rule with an old CIDR is revoked and
      the new CIDR authorized with the client tag
    - test_security_group_update_invalid_client: 'bad client!' raises ValueError before any AWS
      calls
    """
    client = client_tag_value(client)
    if ec2 is None:
        ec2 = boto3.client('ec2')
    if cidrs is None:
        desired_cidrs = discover_client_cidrs(
            v4_subnet_length=v4_subnet_length,
            v6_subnet_length=v6_subnet_length,
        )
    else:
        desired_cidrs = []
        for cidr in cidrs:
            desired_cidrs.append(str(ipaddress.ip_network(cidr, strict=False)))
    desired_set = set()
    for cidr in desired_cidrs:
        desired_set.add(('tcp', DATABASE_PORT, DATABASE_PORT, cidr))
    rule_description = f'rpkilog db access for client {client}'
    retdict = {}
    for group in security_groups_find(ec2=ec2):
        group_id = group['GroupId']
        stale_ingress_rule_ids = []
        stale_egress_rule_ids = []
        keep_set = set()
        for rule in security_group_rules_list(ec2=ec2, group_id=group_id):
            tags = rule_tags_as_dict(rule)
            if tags.get(RULE_CLIENT_TAG_KEY) != client:
                continue
            if rule['IsEgress']:
                stale_egress_rule_ids.append(rule['SecurityGroupRuleId'])
                continue
            rule_cidr = rule.get('CidrIpv4') or rule.get('CidrIpv6')
            if rule_cidr is not None:
                rule_cidr = str(ipaddress.ip_network(rule_cidr, strict=False))
            rule_tuple = (rule.get('IpProtocol'), rule.get('FromPort'), rule.get('ToPort'), rule_cidr)
            if rule_tuple in desired_set and rule_tuple not in keep_set:
                keep_set.add(rule_tuple)
            else:
                stale_ingress_rule_ids.append(rule['SecurityGroupRuleId'])
        add_tuples = desired_set - keep_set
        if len(stale_ingress_rule_ids) > 0:
            ec2.revoke_security_group_ingress(
                GroupId=group_id,
                SecurityGroupRuleIds=stale_ingress_rule_ids,
            )
        if len(stale_egress_rule_ids) > 0:
            ec2.revoke_security_group_egress(
                GroupId=group_id,
                SecurityGroupRuleIds=stale_egress_rule_ids,
            )
        created_cidrs = []
        ipv4_ranges = []
        ipv6_ranges = []
        for add_tuple in sorted(add_tuples, key=lambda rule_tuple: rule_tuple[3]):
            cidr = add_tuple[3]
            created_cidrs.append(cidr)
            if ipaddress.ip_network(cidr).version == 4:
                ipv4_ranges.append({'CidrIp': cidr, 'Description': rule_description})
            else:
                ipv6_ranges.append({'CidrIpv6': cidr, 'Description': rule_description})
        if len(ipv4_ranges) > 0 or len(ipv6_ranges) > 0:
            permission = {'IpProtocol': 'tcp', 'FromPort': DATABASE_PORT, 'ToPort': DATABASE_PORT}
            if len(ipv4_ranges) > 0:
                permission['IpRanges'] = ipv4_ranges
            if len(ipv6_ranges) > 0:
                permission['Ipv6Ranges'] = ipv6_ranges
            ec2.authorize_security_group_ingress(
                GroupId=group_id,
                IpPermissions=[permission],
                TagSpecifications=[{
                    'ResourceType': 'security-group-rule',
                    'Tags': [{'Key': RULE_CLIENT_TAG_KEY, 'Value': client}],
                }],
            )
        removed_rule_ids = stale_ingress_rule_ids + stale_egress_rule_ids
        if len(created_cidrs) == 0 and len(removed_rule_ids) == 0:
            logger.info(f'{group_id} already up to date for client={client}: {sorted(desired_cidrs)}')
        else:
            logger.info(
                f'{group_id} client={client}: removed {len(removed_rule_ids)} stale rule(s), '
                f'created rules for {created_cidrs}'
            )
        retdict[group_id] = {'created': created_cidrs, 'removed': removed_rule_ids}
    return retdict


def format_table(headers: list[str], rows: list[list]) -> str:
    """
    Format rows into fixed-width columns with two-space separators and a header line.

    TOTEST:
    - test_format_table: widths follow the longest cell per column; trailing whitespace stripped
    """
    widths = []
    for column_index in range(len(headers)):
        width = len(headers[column_index])
        for row in rows:
            if len(str(row[column_index])) > width:
                width = len(str(row[column_index]))
        widths.append(width)
    lines = []
    header_parts = []
    for column_index in range(len(headers)):
        header_parts.append(headers[column_index].ljust(widths[column_index]))
    lines.append('  '.join(header_parts).rstrip())
    for row in rows:
        row_parts = []
        for column_index in range(len(headers)):
            row_parts.append(str(row[column_index]).ljust(widths[column_index]))
        lines.append('  '.join(row_parts).rstrip())
    retstr = '\n'.join(lines)
    return retstr


def security_group_show(ec2=None) -> str:
    """
    Render a human-friendly table of all rules in the CLI-managed Security Group(s).
    """
    if ec2 is None:
        ec2 = boto3.client('ec2')
    headers = ['GROUP-ID', 'GROUP-NAME', 'RULE-ID', 'DIR', 'PROTO', 'PORTS', 'CIDR', 'CLIENT', 'DESCRIPTION']
    rows = []
    for group in security_groups_find(ec2=ec2):
        for rule in security_group_rules_list(ec2=ec2, group_id=group['GroupId']):
            tags = rule_tags_as_dict(rule)
            if rule['IsEgress']:
                direction = 'egress'
            else:
                direction = 'ingress'
            protocol = rule.get('IpProtocol', '')
            if protocol == '-1':
                protocol = 'all'
            cidr = rule.get('CidrIpv4') or rule.get('CidrIpv6')
            if cidr is None:
                referenced_group = rule.get('ReferencedGroupInfo')
                if referenced_group is not None:
                    cidr = referenced_group.get('GroupId', '?')
                else:
                    cidr = rule.get('PrefixListId', '?')
            from_port = rule.get('FromPort')
            to_port = rule.get('ToPort')
            if from_port is None or from_port == -1:
                ports = 'all'
            elif from_port == to_port:
                ports = str(from_port)
            else:
                ports = f'{from_port}-{to_port}'
            rows.append([
                group['GroupId'],
                group.get('GroupName', ''),
                rule['SecurityGroupRuleId'],
                direction,
                protocol,
                ports,
                cidr,
                tags.get(RULE_CLIENT_TAG_KEY, ''),
                rule.get('Description') or '',
            ])
    retstr = format_table(headers=headers, rows=rows)
    return retstr


def security_group_iam_policy() -> dict:
    """
    IAM policy document covering the show/update functionality.  Single source of truth for the
    `permissions` subcommand's JSON and HCL renderings.  Modify actions are split across two
    statements because aws:ResourceTag is evaluated against each resource in the request: the
    security-group statement carries the cli_managed=True condition (so the grantee can only
    touch CLI-managed Security Groups, not the Terraform-managed sibling), while the
    security-group-rule statement is unconditioned -- rules only carry client=<name> tags, and
    rule ARNs are only ever authorized alongside their parent group, which the tag condition
    gates.  The CreateTags grant is what lets authorize_security_group_ingress tag the new rules.
    """
    retdict = {
        'Version': '2012-10-17',
        'Statement': [
            {
                'Sid': 'DescribeSecurityGroupsAndRules',
                'Effect': 'Allow',
                'Action': [
                    'ec2:DescribeSecurityGroupRules',
                    'ec2:DescribeSecurityGroups',
                ],
                'Resource': '*',
            },
            {
                'Sid': 'ModifyTaggedSecurityGroups',
                'Effect': 'Allow',
                'Action': [
                    'ec2:AuthorizeSecurityGroupIngress',
                    'ec2:RevokeSecurityGroupEgress',
                    'ec2:RevokeSecurityGroupIngress',
                ],
                'Resource': 'arn:aws:ec2:*:*:security-group/*',
                'Condition': {
                    'StringEquals': {
                        f'aws:ResourceTag/{CLI_MANAGED_TAG_KEY}': CLI_MANAGED_TAG_VALUE,
                    },
                },
            },
            {
                'Sid': 'ModifyRulesInTaggedSecurityGroups',
                'Effect': 'Allow',
                'Action': [
                    'ec2:AuthorizeSecurityGroupIngress',
                    'ec2:RevokeSecurityGroupEgress',
                    'ec2:RevokeSecurityGroupIngress',
                ],
                'Resource': 'arn:aws:ec2:*:*:security-group-rule/*',
            },
            {
                'Sid': 'TagRulesOnCreate',
                'Effect': 'Allow',
                'Action': ['ec2:CreateTags'],
                'Resource': 'arn:aws:ec2:*:*:security-group-rule/*',
                'Condition': {
                    'StringEquals': {'ec2:CreateAction': 'AuthorizeSecurityGroupIngress'},
                },
            },
        ],
    }
    return retdict


def hcl_expression(value, indent: int = 0) -> str:
    """
    Render a python structure as an HCL expression, e.g. for the argument of jsonencode(...).
    Object keys are always quoted, which HCL permits and which keeps keys like
    "ec2:CreateAction" valid.

    TOTEST:
    - test_hcl_expression_scalars: strings/numbers/bools render as JSON literals
    - test_hcl_expression_nested: a dict containing a list of dicts renders with quoted keys,
      ``=`` separators, and 2-space indentation per level
    """
    pad = '  ' * indent
    child_pad = '  ' * (indent + 1)
    if isinstance(value, dict):
        lines = ['{']
        for key in value:
            rendered = hcl_expression(value[key], indent=indent + 1)
            lines.append(f'{child_pad}{json.dumps(key)} = {rendered}')
        lines.append(pad + '}')
        retstr = '\n'.join(lines)
    elif isinstance(value, list):
        lines = ['[']
        for item in value:
            rendered = hcl_expression(item, indent=indent + 1)
            lines.append(f'{child_pad}{rendered},')
        lines.append(pad + ']')
        retstr = '\n'.join(lines)
    else:
        retstr = json.dumps(value)
    return retstr


def security_group_permissions_text() -> str:
    """
    Render the IAM permissions needed by show/update as JSON and as a Terraform aws_iam_policy.
    """
    policy = security_group_iam_policy()
    json_text = json.dumps(policy, indent=2)
    hcl_text = (
        'resource "aws_iam_policy" "rpkilog_database_security_group" {\n'
        '  name   = "rpkilog_database_security_group"\n'
        f'  policy = jsonencode({hcl_expression(policy, indent=1)})\n'
        '}'
    )
    retstr = f'# IAM policy (JSON)\n{json_text}\n\n# Terraform (HCL)\n{hcl_text}'
    return retstr


def database_security_group_cli_entry_point():
    """
    Parse CLI arguments and dispatch to the requested database-security-group subcommand.
    """
    logging.basicConfig(
        datefmt='%Y-%m-%dT%H:%M:%S',
        format='%(asctime)s.%(msecs)03d %(filename)s %(lineno)d %(funcName)s %(levelname)s %(message)s',
        level=logging.INFO,
    )
    ap1 = argparse.ArgumentParser(
        description='Maintain rules in the Security Group(s) tagged '
                    f'{SECURITY_GROUP_TAG_KEY}={SECURITY_GROUP_TAG_VALUE} and '
                    f'{CLI_MANAGED_TAG_KEY}={CLI_MANAGED_TAG_VALUE} which allow clients to '
                    'reach the RDS database',
    )
    ap1.add_argument('--debug', action='store_true', help='Break to debugger after parsing arguments')
    subparsers = ap1.add_subparsers(dest='subparser_name', required=True)
    subparsers.add_parser(
        'show',
        description='List rules in all internet_database Security Groups, including the '
                    'Terraform-managed one',
    )
    ap_update = subparsers.add_parser(
        'update',
        description="Replace this client's rules with its current (or given) addresses",
    )
    ap_update.add_argument(
        '--client', required=True, type=client_tag_value,
        help='client name recorded in rule tags; existing rules tagged client=<value> are replaced',
    )
    ap_update.add_argument(
        '--cidr', action='append', dest='cidrs', metavar='CIDR',
        help="IPv4/IPv6 CIDR to allow instead of discovering this host's addresses (repeatable)",
    )
    ap_update.add_argument(
        '--v4-subnet-length', type=int,
        help='widen the discovered IPv4 address to this prefix length (default: 32)',
    )
    ap_update.add_argument(
        '--v6-subnet-length', type=int,
        help='widen the discovered IPv6 address to this prefix length, e.g. 56 for a SOHO '
             'delegation (default: 128)',
    )
    subparsers.add_parser(
        'permissions',
        description='Print the IAM permissions needed by show/update, in JSON and Terraform HCL',
    )
    args = ap1.parse_args()
    if args.debug:
        breakpoint()
    log_startup_args(args=args, secret_dests=set())
    match args.subparser_name:
        case 'show':
            print(security_group_show())
        case 'update':
            if args.cidrs is not None and (args.v4_subnet_length is not None or args.v6_subnet_length is not None):
                ap1.error('--v4-subnet-length/--v6-subnet-length apply only to discovery; not valid with --cidr')
            v4_subnet_length = 32
            if args.v4_subnet_length is not None:
                v4_subnet_length = args.v4_subnet_length
            v6_subnet_length = 128
            if args.v6_subnet_length is not None:
                v6_subnet_length = args.v6_subnet_length
            security_group_update(
                client=args.client,
                cidrs=args.cidrs,
                v4_subnet_length=v4_subnet_length,
                v6_subnet_length=v6_subnet_length,
            )
        case 'permissions':
            print(security_group_permissions_text())
