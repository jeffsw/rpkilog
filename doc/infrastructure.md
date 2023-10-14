The back-end infrastructure for rpkilog is intended to deploy into AWS using Terraform.  In this document,
any tasks that need to be performed manually will be listed.  Some of these might be to-do items
if it's practical to automate them.

# AWS Bootstrap

* Create `superuser` IAM group and attach policy `AdministratorAccess`
* Create initial IAM user (mine), retrieve credentials
* Domain registration -- `rpkilog.com` is manually registered within our AWS account

# Terraform invocation

With the above bootstrap tasks complete, terraform invocation should be possible.

# ElasticSearch

Note: it is expected that the AWS console root user will not be able to display the full ES cluster health
information.  Use an IAM user with superuser membership, not the root user.

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

