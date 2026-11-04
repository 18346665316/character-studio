#!/usr/bin/env python3
"""Single-call loopback Studio client. No mutation retries or generation loop."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import secrets
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def clean(value):
    if isinstance(value, dict):
        return {k:clean(v) for k,v in value.items() if k.lower() not in ('token','api_key','authorization')}
    if isinstance(value, list): return [clean(v) for v in value]
    return value


def append(path, event):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a',encoding='utf-8') as stream:
        stream.write(json.dumps(dict(time=datetime.now(timezone.utc).isoformat(),**event),ensure_ascii=False)+'\n')
        stream.flush()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True,type=Path)
    parser.add_argument('--url',help='Explicit loopback URL, otherwise read .local/panel/server.json')
    parser.add_argument('--timeout',type=float,default=60)
    parser.add_argument('method',choices=['get','post','download'])
    parser.add_argument('route')
    parser.add_argument('--data',type=Path)
    parser.add_argument('--journal',type=Path,help='Required for POST; records intent before sending')
    parser.add_argument('--out',type=Path)
    args=parser.parse_args()
    if not (args.root/'pipeline/panel.py').is_file(): parser.error('--root must point to the Studio repository')
    if not args.route.startswith('/') or args.route.startswith('//') or '#' in args.route:
        parser.error('route must be an absolute local path, without fragment')
    if args.out and args.out.exists(): parser.error('--out already exists; use a new filename')
    if args.method=='post' and (not args.data or not args.journal): parser.error('POST requires --data and --journal')
    if args.method=='download' and not args.out: parser.error('download requires --out')
    if args.method!='post' and (args.data or args.journal): parser.error('--data/--journal apply only to POST')
    if not 0<args.timeout<=300: parser.error('timeout must be >0 and <=300 seconds')
    base=args.url or json.loads((args.root/'.local/panel/server.json').read_text())['url']
    parsed=urlparse(base)
    if (parsed.scheme!='http' or parsed.hostname not in ('127.0.0.1','localhost','::1')
            or parsed.username or parsed.password or parsed.path not in ('','/') or parsed.query or parsed.fragment):
        parser.error('Studio URL must be an HTTP loopback origin')
    origin=base.rstrip('/');opener=build_opener(NoRedirect())
    def request(route, data=None, token=None):
        headers={'Accept':'application/json'}
        if data is not None: headers.update({'Content-Type':'application/json','X-Studio-Token':token})
        return opener.open(Request(origin+route,data=data,headers=headers),timeout=args.timeout)
    intent=None
    try:
        raw=None;token=None
        if args.method=='post':
            value=json.loads(args.data.read_text())
            if not isinstance(value,dict): parser.error('--data must contain a JSON object')
            raw=json.dumps(value,ensure_ascii=False).encode()
            with request('/api/projects/state') as response: token=json.load(response)['token']
            intent=secrets.token_hex(8)
            append(args.journal,dict(event='intent',call=intent,origin=origin,route=args.route,request_sha256=hashlib.sha256(raw).hexdigest()))
        with request(args.route,raw,token) as response:
            body=response.read();content_type=response.headers.get_content_type()
        if args.method=='download': output=body
        else:
            value=clean(json.loads(body))
            output=(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode()
        if intent:
            append(args.journal,dict(event='response',call=intent,result=clean(value)))
        if args.out:
            args.out.parent.mkdir(parents=True,exist_ok=True)
            with args.out.open('xb') as stream: stream.write(output)
            print(str(args.out))
        else: sys.stdout.write(output.decode())
        return 0
    except HTTPError as error:
        # Server responses are explicit rejection; never automatically retry.
        try: detail=clean(json.loads(error.read()))
        except (ValueError,UnicodeError): detail={'error':'Non-JSON HTTP error'}
        if intent: append(args.journal,dict(event='http_error',call=intent,status=error.code,detail=detail,retry=False))
        print(json.dumps({'status':error.code,**detail},ensure_ascii=False),file=sys.stderr)
        return 1
    except (OSError,URLError,ValueError,KeyError) as error:
        if intent: append(args.journal,dict(event='uncertain',call=intent,error_type=type(error).__name__,retry=False))
        print(f'{type(error).__name__}: {error}. No automatic retry; inspect saved task state before another POST.' if intent else str(error),file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
