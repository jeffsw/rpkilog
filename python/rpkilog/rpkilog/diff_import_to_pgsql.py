import argparse

# TODO: lots
# import pg8000.native


def cli_entry_point(passed_args):
    ap = argparse.ArgumentParser()
    ap.add_argument('--debug', action='store_true', help='Break to debugger upon start')
    ap.add_argument('--import-files', nargs='+', action='extend')
    args = ap.parse_args(passed_args)

    if args.debug:
        import pdb
        pdb.set_trace()
