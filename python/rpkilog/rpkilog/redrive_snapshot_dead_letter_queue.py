# TODO: create a cli_entry_point and associated other functions to read messages from an AWS SQS queue
#   (example name lambda_dlq_for_vrp_cache_diff), extracting an S3 bucket and key name from the queued
#   events, and running a CLI program (example name `rpkilog-vrp-cache-differ`) for each queued event.
#     1. accept command line arguments as follows
#       a. --sqs-name <SQS queue name>
#       b. --program <program to run, default rpkilog-vrp-cache-differ>
#       c. --debug (immediately breakpoint() to debugger)
#       d. --dry-run don't invoke the given CLI program, but show what would have been invoked, and exit
#       e. --check-exit-code (default true) stop processing upon the first instance of the program exiting
#          with a non-zero exit code
#       f. --timeout in seconds (default 3600) for each subprocess invocation; if one exceeds the given
#          time, stop processing further files, summarize, and exit
#     2. allow stdout & stderr from the invoked programs to pass through to the top-level stdout / stderr.
#        No need to capture these.
#     3. if the subprocess appeared to succeed on a queued S3 file key (non-zero exit code), remove the
#        related SQS queue entry.  If a subprocess was unsuccessful, don't remove the SQS entry.
#     4. report a summary of the S3 key names processed before exiting the main program
# Only modify this file.  Don't change any other project files.
#
# An example of the events in the SQS queue is below:
# {
#     "Records" : [
#         {
#             "awsRegion" : "us-east-1",
#             "eventName" : "ObjectCreated:Put",
#             "eventSource" : "aws:s3",
#             "eventTime" : "2026-05-08T13:40:18.113Z",
#             "eventVersion" : "2.1",
#             "requestParameters" : {
#                 "sourceIPAddress" : "184.56.11.81"
#             },
#             "responseElements" : {
#                 "x-amz-id-2" : "zRux8fu0uFCymmd9Yrl1Y4ufnlrJ/s4gw77+YCk5A2O11NLqsOaFoL0fXQqDJirWW6tjdCiwXMeh51+XE0FQk03ajcCp/4uY",
#                 "x-amz-request-id" : "XPYPMEJ80P43BNSJ"
#             },
#             "s3" : {
#                 "bucket" : {
#                     "arn" : "arn:aws:s3:::rpkilog-snapshot-summary",
#                     "name" : "rpkilog-snapshot-summary",
#                     "ownerIdentity" : {
#                         "principalId" : "A1NJQJ8DKQNCWC"
#                     }
#                 },
#                 "configurationId" : "tf-s3-lambda-20211215024002188700000001",
#                 "object" : {
#                     "eTag" : "12dc0f221bd13a47924b0687138cb2f6",
#                     "key" : "20260508T133547Z.json.bz2",
#                     "sequencer" : "0069FDE7C13D0B6B4D",
#                     "size" : 3336031
#                 },
#                 "s3SchemaVersion" : "1.0"
#             },
#             "userIdentity" : {
#                 "principalId" : "AWS:AIDAQZMDVGPQGOF5TVBTZ"
#             }
#         }
#     ]
# }
