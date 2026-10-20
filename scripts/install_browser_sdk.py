"""Install the qualified Emscripten archive locally; never change native tools."""
import hashlib
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
RELEASE = 'eb132757325583b787fe9414b09afea9442b72ad'
SHA256 = '3d8ced05935fbef5b3edda4252dce260004860bf8d579617f13d417338aa4cac'
URL = f'https://storage.googleapis.com/webassembly/emscripten-releases-builds/mac/{RELEASE}/wasm-binaries-arm64.tar.xz'


def main():
    if (platform.system(), platform.machine()) != ('Darwin', 'arm64'):
        raise SystemExit('This qualified SDK lock targets macOS arm64. Qualify and separately lock an official archive for another host.')
    sdk = ROOT / '.tools/emsdk'; sdk.mkdir(parents=True, exist_ok=True)
    destination = sdk / 'install'
    node = shutil.which('node')
    if not node:
        raise SystemExit('Node.js is required; no shared runtime is installed by this script.')
    if not destination.exists():
        if shutil.disk_usage(ROOT).free < 3_700_000_000:
            raise SystemExit('Reserve at least 3.7 GB: 286 MB archive + 1.54 GB extraction + free-space reserve.')
        with tempfile.TemporaryDirectory(prefix='sdk-download-', dir=sdk) as td:
            archive = Path(td) / 'sdk.tar.xz'
            subprocess.run(['curl', '--fail', '--location', '--show-error', '--output', str(archive), URL], check=True)
            if hashlib.file_digest(open(archive, 'rb'), 'sha256').hexdigest() != SHA256:
                raise SystemExit('SDK archive digest mismatch; nothing installed.')
            with tarfile.open(archive) as tar:
                tar.extractall(sdk, filter='data')
    emscripten = destination / 'emscripten'
    config = sdk / '.emscripten'
    config.write_text('\n'.join(f'{key} = {value!r}' for key,value in {
        'LLVM_ROOT': str(destination/'bin'), 'BINARYEN_ROOT': str(destination),
        'EMSCRIPTEN_ROOT': str(emscripten), 'NODE_JS': [node], 'CACHE': str(sdk/'cache'),
    }.items()) + '\n')
    version = subprocess.check_output([str(emscripten/'em++'), '--version'], env={**os.environ,'EM_CONFIG':str(config)}, text=True)
    if '6.0.13-git (e13ee988ce3d87a738dd8f3661d02223308c412a)' not in version:
        raise SystemExit('Installed compiler differs from the qualified version.')
    print(version.splitlines()[0])

if __name__ == '__main__':
    main()
