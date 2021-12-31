The back-end infrastructure for rpkilog is intended to deploy into AWS using Terraform.  In this document,
any tasks that need to be performed manually will be listed.  Some of these might be to-do items
if it's practical to automate them.

# AWS Bootstrap

* Create `superuser` IAM group and attach policy `AdministratorAccess`
* Create initial IAM user (mine), retrieve credentials, and set SSH key
* Domain registration -- `rpkilog.com` is manually registered within our AWS account

# Terraform invocation

With the above bootstrap tasks complete, terraform invocation should be possible.

# ElasticSearch

Note: it is expected that the AWS console root user will not be able to display the full ES cluster health
information.  Use an IAM user with superuser membership, not the root user.

Manual processes involved in setting up our ES include:

* Certificate manager -- `es-prod.rpkilog.com` has been manually created & approved
* Create Cognito users and join them to the appropriate Cognito group -- can be automated via AWS API
* Setup ES **Backend role** mappings from IAM roles to ES roles
    * Add to ES `all_access` the IAM roles and users who need full access to the ES domain:
        * `role/es_master` so Cognito users in the Cognito `es_master` group will have full ES access
        * `role/superuser` and other roles used by Cognito users (if any)
        * `user/jeffsw6@gmail.com` and other individual people
    * Add to ES `logstash` the IAM roles: `lambda_vrp_diff_import`
    * Create ES `anonymous` role and add IAM role mapping from IAM role `anonymous_web`
* (!) I've had to `terraform import aws_cognito_user_pool_client.es us-east-1_<pool_-_id>/<client_id>`.
