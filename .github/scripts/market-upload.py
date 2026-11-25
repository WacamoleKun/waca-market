"""Assemble data-only APK chunks. Never execute contents supplied by an upload."""
import base64
import hashlib
import http.client
import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

MAX_BYTES = 512 * 1024 * 1024
PART_BYTES = 16 * 1024 * 1024


def validate_manifest(item):
    if item.get('schemaVersion') != 1 or not isinstance(item.get('sizeBytes'), int) or isinstance(item['sizeBytes'], bool):
        raise ValueError('Manifest inválido')
    if not 1 <= item['sizeBytes'] <= MAX_BYTES or not re.fullmatch('[a-f0-9]{64}', item.get('sha256', '')):
        raise ValueError('Tamaño o huella inválidos')
    parts = item.get('parts')
    if not isinstance(parts, list) or not 1 <= len(parts) <= 32:
        raise ValueError('Partes inválidas')
    for index, part in enumerate(parts):
        expected = min(PART_BYTES, item['sizeBytes'] - index * PART_BYTES)
        if part.get('size') != expected or not 1 <= expected <= PART_BYTES:
            raise ValueError('Tamaño de parte inválido')
        if not re.fullmatch('[a-f0-9]{40}', part.get('blob', '')) or not re.fullmatch('[a-f0-9]{64}', part.get('sha256', '')):
            raise ValueError('Huella de parte inválida')
    if sum(part['size'] for part in parts) != item['sizeBytes']:
        raise ValueError('Faltan partes')
    return item


def assemble(manifest, read_blob, destination):
    validate_manifest(manifest)
    total_hash = hashlib.sha256()
    with open(destination, 'wb') as output:
        for part in manifest['parts']:
            data = read_blob(part['blob'])
            if len(data) != part['size'] or hashlib.sha256(data).hexdigest() != part['sha256']:
                raise ValueError('Una parte no coincide con el archivo original')
            total_hash.update(data)
            output.write(data)
    if total_hash.hexdigest() != manifest['sha256']:
        raise ValueError('La huella final no coincide')


def upload_asset_name(digest):
    # A failed GitHub upload can leave a starter asset. A fresh attempt must not
    # collide with that name or delete an existing published file.
    return "waca-" + digest + "-" + uuid.uuid4().hex + ".apk"


def main():
    repo = os.environ['GITHUB_REPOSITORY']
    if repo != 'WacamoleKun/waca-market':
        raise ValueError('Repositorio no permitido')
    token = os.environ['GH_TOKEN']
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    payload = event.get('client_payload', {})
    ref, commit = payload.get('ref', ''), payload.get('commit', '')
    if not re.fullmatch('market-upload-[a-f0-9]{32}', ref) or not re.fullmatch('[a-f0-9]{40}', commit):
        raise ValueError('Solicitud inválida')

    def api(path, body=None, method=None):
        request = urllib.request.Request('https://api.github.com/repos/' + repo + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
                     'Content-Type': 'application/json', 'User-Agent': 'Waca-Market'}, method=method)
        with urllib.request.urlopen(request, timeout=90) as response:
            raw = response.read(35 * 1024 * 1024 + 1)
            if len(raw) > 35 * 1024 * 1024:
                raise ValueError('Respuesta demasiado grande')
            return json.loads(raw) if raw else {}

    def content(path):
        item = api('/contents/' + path + '?ref=' + commit)
        if item.get('size', 0) > 65536:
            raise ValueError('Manifest demasiado grande')
        return json.loads(base64.b64decode(item['content']))

    current = api('/git/ref/heads/' + ref)
    if current['object']['sha'] != commit:
        raise ValueError('La solicitud cambió; no se procesa')
    try:
        manifest = validate_manifest(content('upload.json'))
        release = api('/releases/tags/catalogo')
        wanted = upload_asset_name(manifest['sha256'])
        assets = []
        for page in range(1, 21):
            batch = api('/releases/' + str(release['id']) + '/assets?per_page=100&page=' + str(page))
            assets.extend(batch)
            if len(batch) < 100:
                break
        existing = next((a for a in assets if a.get('digest') == 'sha256:' + manifest['sha256'] and a['size'] == manifest['sizeBytes']), None)
        if not existing:
            with tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / 'upload.apk'
                def read_blob(sha):
                    blob = api('/git/blobs/' + sha)
                    return base64.b64decode(blob['content'])
                assemble(manifest, read_blob, target)
                connection = http.client.HTTPSConnection('uploads.github.com', timeout=180)
                try:
                    path = '/repos/' + repo + '/releases/' + str(release['id']) + '/assets?name=' + urllib.parse.quote(wanted)
                    connection.putrequest('POST', path)
                    for name, value in {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/vnd.android.package-archive',
                                        'Content-Length': str(manifest['sizeBytes']), 'User-Agent': 'Waca-Market'}.items():
                        connection.putheader(name, value)
                    connection.endheaders()
                    with open(target, 'rb') as source:
                        while block := source.read(1024 * 1024):
                            connection.send(block)
                    response = connection.getresponse()
                    asset = json.loads(response.read(65536))
                    if response.status != 201 or asset.get('digest') != 'sha256:' + manifest['sha256'] or asset.get('size') != manifest['sizeBytes']:
                        raise ValueError('No se pudo verificar la APK alojada')
                finally:
                    connection.close()
        # Delete only the disposable branch created for this exact request.
        if api('/git/ref/heads/' + ref)['object']['sha'] == commit:
            api('/git/refs/heads/' + ref, method='DELETE')
        print('APK preparada y verificada. El panel puede publicar el catálogo.')
    except Exception:
        # Keep a short, data-only error for the panel without exposing credentials or payloads.
        try:
            api('/contents/result.json', {'message': 'Error al preparar APK del Market', 'branch': ref,
                'content': base64.b64encode(json.dumps({'status': 'failed', 'message': 'No se pudo preparar la APK. Vuelve a intentar la publicación.'}).encode()).decode()}, 'PUT')
        except Exception:
            pass
        raise


if __name__ == '__main__':
    main()
