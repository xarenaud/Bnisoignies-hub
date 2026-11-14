"""Deploy only to a document root verified against the requested public hostname."""
import os,io,secrets,urllib.request,time
from pathlib import Path
host=os.environ['OVH_HOST'];user=os.environ['OVH_USERNAME'];password=os.environ['OVH_PASSWORD'];port=int(os.environ.get('OVH_PORT') or 21)
base='www';marker='bni-site-check-'+secrets.token_hex(12)+'.txt';token=secrets.token_hex(24)
if port==21:
    import ftplib
    ftp=ftplib.FTP_TLS();ftp.connect(host,port,timeout=25)
    try:
        ftp.login(user,password);ftp.prot_p()
    except ftplib.error_perm as exc:
        if not str(exc).startswith("500"):raise
        # Same legacy FTP transport as the existing, working OVH deployment.
        ftp.close();ftp=ftplib.FTP();ftp.connect(host,port,timeout=25);ftp.login(user,password)
    ftp.cwd(base)
    put=lambda name,data:ftp.storbinary('STOR '+name,io.BytesIO(data))
    delete=lambda name:ftp.delete(name)
else:
    import paramiko
    ssh=paramiko.SSHClient();ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy());ssh.connect(host,port=port,username=user,password=password,timeout=25);ftp=ssh.open_sftp();ftp.chdir(base)
    def put(name,data):
        with ftp.open(name,'wb') as f:f.write(data)
        ftp.chmod(name,0o644)
    delete=lambda name:ftp.remove(name)
put(marker,token.encode())
try:
    with urllib.request.urlopen('https://www.bim-soignies.be/'+marker,timeout=30) as response:
        if response.read().decode()!=token:raise RuntimeError('Document root verification failed; no site files changed.')
finally:delete(marker)
# Deliberately no mirror/delete: preserve every unrelated application and file.
for name in ['logo.svg','vitralux.html','index.html']:put(name,Path('website',name).read_bytes())
ftp.close()
with urllib.request.urlopen('https://www.bim-soignies.be/?release='+token,timeout=30) as response:
    html=response.read().decode()
    assert '<title>BNI Soignies BIM' in html and '/api/public/website' in html
print('Verified public site at https://www.bim-soignies.be')
