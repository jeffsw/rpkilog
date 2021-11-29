import argparse
import boto3
import logging
import os
from pathlib import Path
import re
import tarfile
import yaml

config = dict()
logger = logging.getLogger(__name__)

class IngestTar():

    @classmethod
    def extract_useful_json(cls, input_tar:Path, json_data_dir:Path):
        logger.info(F'Extracting useful JSON data from {input_tar}')
        tf = tarfile.open(name=input_tar, mode='r')
        for member in tf.getmembers():
            if not member.name.endswith('rpki-client.json'):
                continue
            if not member.isfile():
                raise ValueError(F'rpki-client.json is not a file according to TarInfo.isfile()')
            rem = re.match(r'^rpki-(\d{8}T\d{6}Z)/output/rpki-client.json$', member.name)
            if not rem:
                raise ValueError(F'regex failed to match tar member name: F{member.name}')
            output_tmp = Path(json_data_dir, rem.group(1) + '.tmp')
            output_json = Path(json_data_dir, rem.group(1) + '.json')
            ef = tf.extractfile(member)
            output_file = open(output_tmp, 'xb')
            output_file.write(ef.read())
            output_file.close()
            os.rename(output_tmp, output_json)
            return output_json
        else:
            raise KeyError(F'rpki-client.json not found in TAR file {input_tar}')

    @classmethod
    def aws_lambda_entry_point(cls, event, context):
        logging.basicConfig()
        s3 = boto3.client('s3')
        dst_bucket = os.getenv('snapshot_summary_bucket')
        src_bucket = event['Records'][0]['s3']['bucket']['name']
        s3_obj_key = event['Records'][0]['s3']['object']['key']
        rem = re.search(r'(?P<datetime>(?P<date>\d{8})T(?P<time>\d{4,6})Z)\.(tar|tgz)$', s3_obj_key)
        if rem:
            dst_file_name = F'{rem.group("datetime")}.json'
        else:
            raise ValueError(F'Unexpected input file name didnt match our regex: {s3_obj_key}')
        tar_file_basename = Path(s3_obj_key).name
        tar_file_path = Path('/tmp', tar_file_basename)
        s3.download_file(
            Bucket=src_bucket,
            Key=s3_obj_key,
            Filename=str(tar_file_path),
        )
        logging.info(F'Downloaded file {s3_obj_key}')
        json_file_path = cls.extract_useful_json(input_tar=tar_file_path, json_data_dir=Path('/tmp'))
        logging.info(F'Extracted JSON data to {json_file_path}')
        s3.upload_file(
            Filename=str(json_file_path),
            Bucket=dst_bucket,
            Key=json_file_path.name,
        )
        logging.info(F'Uploaded to s3://{dst_bucket}/{json_file_path.name}')

    @classmethod
    def cli_entry_point(cls):
        global config
        logging.basicConfig()
        ap = argparse.ArgumentParser(argument_default=argparse.SUPPRESS)
        ap.add_argument('--config-file', type=Path, help='Configuration file in YAML format')
        ap.add_argument('--input-tar', required=True, type=Path, help='Input TAR file (may be .tar.gz, .tgz, .tar.bz2, etc.)')
        ap.add_argument('--json-data-dir', type=Path, help='Directory for storing JSON data files extracted from TAR.')
        ap.add_argument('--log-level', type=str, help='Log level.  Try CRITICAL, ERROR, or DEBUG.  Default is INFO.')
        args = vars(ap.parse_args())
        if 'config_file' in args:
            args['config_file'] = args['config_file'].expanduser()
            yaml_file = open(args['config_file'], 'r')
        else:
            # default config location
            try:
                yaml_path = Path(Path.home(), '.rpkilog', 'ingest_tar.yml')
                yaml_file = open(yaml_path, 'r')
            except:
                pass
        if yaml_file:
            config = yaml.safe_load(yaml_file)
        if 'log_level' in args:
            logger.setLevel(args['log_level'])
        else:
            logger.setLevel('INFO')
        config.update(args)
        for k in ['input_tar', 'json_data_dir']:
            if not isinstance(config[k], Path):
                config[k] = Path(config[k])
            config[k] = config[k].expanduser()

        json_file_path = cls.extract_useful_json(input_tar=args['input_tar'], json_data_dir=config['json_data_dir'])
        logging.info(F'Extracted JSON data to {json_file_path}')
