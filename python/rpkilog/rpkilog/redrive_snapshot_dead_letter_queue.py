import argparse
import dataclasses
import json
import logging
import subprocess
import time

import boto3

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class RedriveSnapshotResult:
    s3_key: str
    duration_seconds: float
    sqs_entry: dict
    s3_event: dict
    completed_process: subprocess.CompletedProcess | None = None
    timed_out: bool = False

    @property
    def succeeded(self) -> bool:
        return not self.timed_out and self.completed_process is not None and self.completed_process.returncode == 0


def receive_all_messages(sqs_client, queue_url):
    """Yield all visible messages from the queue, stopping when none remain."""
    while True:
        response = sqs_client.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=0,
        )
        messages = response.get('Messages', [])
        if not messages:
            break
        yield from messages


def s3_events_from_message(message):
    """Yield (bucket_name, object_key, record) tuples extracted from an SQS message body."""
    body = json.loads(message['Body'])
    for record in body.get('Records', []):
        bucket = record['s3']['bucket']['name']
        key = record['s3']['object']['key']
        yield bucket, key, record


def cli_entry_point():
    logging.basicConfig(
        level='INFO',
        datefmt='%Y-%m-%dT%H:%M:%S',
        format='%(asctime)s.%(msecs)03d %(filename)s %(lineno)d %(funcName)s %(levelname)s %(message)s',
    )

    ap = argparse.ArgumentParser(description='Redrive an S3-event SQS dead-letter queue.')
    ap.add_argument('--sqs-name', default="lambda_dlq_for_vrp_cache_diff",
                    help='SQS queue name (default: lambda_dlq_for_vrp_cache_diff)')
    ap.add_argument('--program', default='rpkilog-vrp-cache-differ',
                    help='Program to invoke for each queued event (default: rpkilog-vrp-cache-differ)')
    ap.add_argument('--debug', action='store_true',
                    help='Break into debugger immediately after argument parsing')
    ap.add_argument('--dry-run', action='store_true',
                    help='Show what would be invoked for each queued event without running, then exit')
    ap.add_argument('--check-exit-code', action=argparse.BooleanOptionalAction, default=True,
                    help='Stop processing on the first non-zero subprocess exit code (default: enabled)')
    ap.add_argument('--timeout', type=int, default=3600,
                    help='Timeout in seconds for each subprocess invocation (default: 3600)')
    ap.add_argument('--prompt', action='store_true',
                    help='Prompt for confirmation before invoking each subprocess; press Y/y to continue, any other key to stop')
    ap.add_argument('--region',
                    help='AWS region where the SQS queue is located; falls back to external configuration if omitted')
    ap.add_argument('extra_args', nargs=argparse.REMAINDER,
                    help='Additional arguments passed through to each subprocess invocation (place after --)')
    args = ap.parse_args()
    extra_args = args.extra_args[1:] if args.extra_args and args.extra_args[0] == '--' else args.extra_args

    if args.debug:
        breakpoint()

    sqs = boto3.client('sqs', **({'region_name': args.region} if args.region else {}))
    queue_url = sqs.get_queue_url(QueueName=args.sqs_name)['QueueUrl']

    results: list[RedriveSnapshotResult] = []
    stop_processing = False

    for message in receive_all_messages(sqs, queue_url):
        if stop_processing:
            break

        message_all_succeeded = True
        for bucket, key, s3_event in s3_events_from_message(message):
            cmd = [args.program, '--summary-bucket', bucket, '--new-file-key', key] + extra_args

            if args.dry_run:
                print(' '.join(cmd))
                continue

            if args.prompt:
                answer = input(f'Invoke: {" ".join(cmd)}\nProceed? [Y/n] ')
                if answer.strip().lower() != 'y':
                    stop_processing = True
                    break

            logger.info('Invoking: %s', ' '.join(cmd))
            t0 = time.monotonic()
            try:
                completed = subprocess.run(cmd, timeout=args.timeout)
                duration = time.monotonic() - t0
                result = RedriveSnapshotResult(s3_key=key, duration_seconds=duration,
                                               sqs_entry=message, s3_event=s3_event,
                                               completed_process=completed)
            except subprocess.TimeoutExpired:
                duration = time.monotonic() - t0
                result = RedriveSnapshotResult(s3_key=key, duration_seconds=duration,
                                               sqs_entry=message, s3_event=s3_event,
                                               timed_out=True)
                logger.error('Subprocess timed out after %ds for key: %s', args.timeout, key)
                results.append(result)
                message_all_succeeded = False
                stop_processing = True
                break

            results.append(result)
            if result.succeeded:
                logger.info('Subprocess succeeded in %.1fs for key: %s', duration, key)
            else:
                logger.error('Subprocess exited with code %d in %.1fs for key: %s',
                             completed.returncode, duration, key)
                message_all_succeeded = False
                if args.check_exit_code:
                    stop_processing = True
                    break

        if not args.dry_run and message_all_succeeded:
            sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=message['ReceiptHandle'])

    if args.dry_run:
        return

    succeeded = [r for r in results if r.succeeded]
    failed = [r for r in results if not r.succeeded]
    logger.info('Summary: %d key(s) succeeded, %d key(s) failed', len(succeeded), len(failed))
    for r in results:
        if r.succeeded:
            logger.info('  succeeded (%.1fs): %s', r.duration_seconds, r.s3_key)
        elif r.timed_out:
            logger.info('  failed - timeout (%.1fs): %s', r.duration_seconds, r.s3_key)
        else:
            returncode = r.completed_process.returncode if r.completed_process else '?'
            logger.info('  failed - exit %s (%.1fs): %s', returncode, r.duration_seconds, r.s3_key)
