"""Verify the public bytes of a reviewed ZIP, including WASM MIME and signature."""
import argparse
import concurrent.futures
import hashlib
import json
import email
import subprocess
import tempfile
import zipfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', required=True)
    parser.add_argument('--zip', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    with zipfile.ZipFile(args.zip) as archive:
        expected = {name: archive.read(name) for name in archive.namelist() if name != '_headers'}

    def check(item):
        name, data = item
        # Use the host's curl TLS/certificate integration; retain certificate checks.
        with tempfile.NamedTemporaryFile() as headers:
            response = subprocess.run(['curl', '--fail', '--silent', '--show-error', '--location',
                                       '--max-time', '30', '--dump-header', headers.name,
                                       args.url.rstrip('/') + '/' + name], capture_output=True, check=True)
            actual = response.stdout
            raw = Path(headers.name).read_text().strip().split('\n\n')[-1]
            parsed = email.message_from_string(raw.split('\n', 1)[1])
            mime = parsed.get('Content-Type', '')
            cache = parsed.get('Cache-Control', '')
        digest = hashlib.sha256(actual).hexdigest()
        ok = digest == hashlib.sha256(data).hexdigest()
        if name.endswith('.wasm'):
            ok = ok and 'application/wasm' in mime and actual[:4] == b'\0asm'
        if name == 'browser/manifest.json':
            ok = ok and 'no-cache' in cache and 'immutable' not in cache
        return {'file': name, 'ok': ok, 'sha256': digest, 'bytes': len(actual), 'mime': mime, 'cache_control': cache}

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(check, expected.items()))
    report = {'url': args.url, 'zip_sha256': hashlib.sha256(args.zip.read_bytes()).hexdigest(),
              'ok': all(row['ok'] for row in results), 'files': len(results), 'results': results}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'results'}))
    if not report['ok']:
        raise SystemExit('Deployed files differ: ' + str([r for r in results if not r['ok']]))


if __name__ == '__main__':
    main()
