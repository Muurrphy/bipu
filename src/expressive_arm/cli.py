"""Offline CLI: no serial access or implicit robot execution."""
import argparse,json,sys
from pathlib import Path
from .trajectory import catalog,inspect,load,crop,write_rows,plot,export_csv

def main(argv=None):
    parser=argparse.ArgumentParser(description='Eight human-choreographed SO-101 expressions (offline tools)')
    subs=parser.add_subparsers(dest='command',required=True)
    subs.add_parser('list');subs.add_parser('validate')
    p=subs.add_parser('inspect');p.add_argument('expression')
    p=subs.add_parser('plot');p.add_argument('expression');p.add_argument('--output',required=True,type=Path)
    p=subs.add_parser('export');p.add_argument('expression');p.add_argument('--output',required=True,type=Path)
    p=subs.add_parser('crop');p.add_argument('expression');p.add_argument('--start',required=True,type=float);p.add_argument('--end',required=True,type=float);p.add_argument('--output',required=True,type=Path)
    args=parser.parse_args(argv)
    try:
        if args.command=='list':
            for e in catalog()['expressions']:print(f"{e['id']:14} {e['name']}  {e['duration_s']:.2f}s")
        elif args.command=='validate':
            for e in catalog()['expressions']:
                rows=load(e['id']);print(f"OK {e['id']}: {len(rows)} frames / checksum verified")
        elif args.command=='inspect':print(json.dumps(inspect(args.expression),ensure_ascii=False,indent=2))
        elif args.command=='plot':plot(args.expression,args.output);print(args.output)
        elif args.command=='export':export_csv(args.expression,args.output);print(args.output)
        elif args.command=='crop':write_rows(crop(load(args.expression),args.start,args.end),args.output);print(args.output)
    except (ValueError,OSError,json.JSONDecodeError) as error:
        parser.exit(2,f'Error: {error}\n')

if __name__=='__main__':main()
