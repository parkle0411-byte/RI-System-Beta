"""Host-side disposable MySQL runner: python3 backend/qa/run_concurrency.py.

Requires Docker and existing backend images. No production data, credentials,
containers or volumes are touched. Optional --image selects a candidate image.
"""
import argparse
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time

parser = argparse.ArgumentParser()
parser.add_argument('--image', default='ri-backend:local')
args = parser.parse_args()
project_root = Path(__file__).resolve().parents[2]
tag = secrets.token_hex(4)
prefix = 'ri-concurrency-'+tag
root = Path(tempfile.mkdtemp(prefix=prefix+'-'))
(root/'secrets').mkdir()
(root/'scripts').mkdir()
for name in ['mysql_root_password','mysql_app_password','mysql_runtime_password','django_secret_key']:
    path = root/'secrets'/name
    path.write_text(secrets.token_hex(32))
    path.chmod(0o644)  # Random test-only secrets must be readable by uid 1001.
compose = (project_root/'qa/ui/compose.uitest.yaml').read_text()
compose = compose.replace('ri-uitest',prefix).replace('ri-ut-',prefix+'-').replace('ri-backend:local',args.image)
compose = compose.replace('secrets: [django_secret_key, mysql_app_password]', 'secrets: [django_secret_key, mysql_app_password, mysql_runtime_password]')
compose = compose.replace('  mysql_app_password: {file:', '  mysql_runtime_password: {file: "${UT_SECRETS:?}/mysql_runtime_password"}\n  mysql_app_password: {file:')
(root/'compose.yaml').write_text(compose)
(root/'scripts/db_harden.sh').write_text((project_root/'scripts/db_harden.sh').read_text().replace('ri-mysql',prefix+'-mysql'))
env = dict(os.environ, UT_SECRETS=str(root/'secrets'))
cmd = ['docker','compose','-f',str(root/'compose.yaml')]

def run(command, **kwargs):
    return subprocess.run(command,cwd=root,env=env,check=True,**kwargs)

print('Disposable QA output:',root,flush=True)
try:
    run(cmd+['up','-d','--wait','mysql','backend'])
    for attempt in range(60):
        result = subprocess.run(['docker','exec',prefix+'-backend','python','manage.py','migrate','--noinput'],capture_output=True,text=True)
        if result.returncode==0:
            break
        time.sleep(2)
    else:
        raise RuntimeError(result.stderr)
    run(['bash','scripts/db_harden.sh'])
    base = ['docker','exec','-i','-e','RI_DISPOSABLE_QA=true','-e','MYSQL_USER=ri_runtime',
        '-e','MYSQL_PASSWORD_FILE=/run/secrets/mysql_runtime_password',prefix+'-backend','python','manage.py','shell']
    result = subprocess.run(base,input=(project_root/'backend/qa/concurrency_guards.py').read_text(),text=True,capture_output=True)
    output = result.stdout+'\n'+result.stderr
    (root/'results.log').write_text(output)
    print(output,flush=True)
    if result.returncode or '23/23 passed' not in output or any(line.startswith('FAIL ') for line in output.splitlines()):
        raise RuntimeError('Concurrency regressions failed; see '+str(root/'results.log'))
finally:
    run(cmd+['down','-v','--remove-orphans'],capture_output=True)
