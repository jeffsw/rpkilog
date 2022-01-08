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
    * Add to ES `logstash` the IAM roles:
        * `ec2_cron`
        * `lambda_vrp_diff_import`
    * Edit the `logstash` role:
        * Add `diff-*` to the index permissions w/ crud & create_index.
    * Create ES `anonymous` role and add IAM role mapping from IAM role `anonymous_web`
* (!) I've had to `terraform import aws_cognito_user_pool_client.es us-east-1_<pool_-_id>/<client_id>`.

## Add additional mapped users

With ES fine-grained access control enabled, IAM users & roles are used only for authentication.  ES
itself makes all authorization determinations based on its own permission system.  This works out great
for IAM roles, which can be mapped to ES roles easily.  That's good for programatric access, e.g. lambda.

To allow IAM users (people) access to ES, it's necessary to add IAM-user-to-ES-role mappings for each
user.  The Kibana UI for configuring those mappings is a little confusing.

Visit Kibana -> Security -> Roles -> <role name> -> Mapped users.  Notice the `User type` column, which
can be either `Backend role` (IAM role) or `User` (IAM user or ES user).

To add user mappings, click `Manage mapping` and type the user's IAM arn into the `Users` input box.  This looks
sketchy but it does work.  Click the `Map` button to save the changes.  Upon returning to the `Maped user`
list, you should see the new entry with `User type = User`.

After that, both ES API queries and AWS Console access to cluster health should work correctly.

AWS has some guidance on using the ES REST API.  This will be a good resource when automating ES user
management.  https://docs.aws.amazon.com/opensearch-service/latest/developerguide/fgac.html#fgac-more-masters

## After importing some data

* In `Stack Management -> Advanced Settings` I changed `Timezone for date fomatting` to `UTC` using the GUI.
* `Stack Management -> Index patterns -> Create index pattern` called `diff-*`
    * Configure it with `observation_timestamp` as the *primary time field* for this index pattern
* Customize the UI in `Stack Management -> Advanced Settings`
    * General
        * Date format: `YYYY-MM-DD T HH:mm:ss ZZ`
        * Timezone for date formatting: `UTC`
        * Date with nanoseconds format: `YYYY-MM-DDTHH:mm:SSSSSSSSSZZ`
        * Dark mode: No (!) It seems less usable.
        * Time filter quick ranges, keep only the following:
            * Today
            * Last 1 hour
            * Last 24 hours
            * Last 7 days
            * Last 30 days
            * Last 90 days
            * Last 1 year
        * Time filter defaults: `Last 7 days`
    * Discover
        * Tie breaker fields: `prefix,maxLength,asn,_doc`
        * Default columns: `prefix,maxLength,asn,verb`
        * Default sort direction: Ascending

