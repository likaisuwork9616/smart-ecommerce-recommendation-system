"""Initialize the project's downloaded MySQL on Windows, without a system service."""
import secrets
import socket
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MYSQL = ROOT / '.runtime' / 'mysql'
TOOLS = ROOT / '.runtime' / 'tools' / 'mysql-8.4.11-winx64'


def main():
    config_path = ROOT / 'scripts' / 'db_config.py'
    if config_path.exists() or (MYSQL / 'data').exists():
        raise SystemExit('Existing database/config detected; setup will not overwrite it.')
    server = TOOLS / 'bin' / 'mysqld.exe'
    if not server.exists():
        raise SystemExit('Extract the official MySQL ZIP into .runtime/tools first.')
    with socket.socket() as probe:
        probe.settimeout(1)
        if probe.connect_ex(('127.0.0.1', 3307)) == 0:
            raise SystemExit('Port 3307 is already occupied; no setup files were changed.')
    MYSQL.mkdir(parents=True, exist_ok=True)
    ini = MYSQL / 'my.ini'
    ini.write_text(
        '[mysqld]\n'
        f'basedir="{TOOLS.as_posix()}"\n'
        f'datadir="{(MYSQL / "data").as_posix()}"\n'
        f'log-error="{(MYSQL / "mysql-error.log").as_posix()}"\n'
        f'pid-file="{(MYSQL / "mysql.pid").as_posix()}"\n'
        'bind-address=127.0.0.1\nport=3307\nmysqlx=OFF\n'
        'character-set-server=utf8mb4\ncollation-server=utf8mb4_unicode_ci\n'
        'innodb-buffer-pool-size=256M\n', encoding='utf-8'
    )
    admin_password = secrets.token_urlsafe(32)
    app_password = secrets.token_urlsafe(32)
    (MYSQL / 'admin.ini').write_text(
        '[client]\nuser=root\n'
        f'password={admin_password}\nhost=127.0.0.1\nport=3307\nprotocol=TCP\n',
        encoding='utf-8'
    )
    init_sql = MYSQL / 'bootstrap.sql'
    init_sql.write_text(
        f"ALTER USER 'root'@'localhost' IDENTIFIED BY '{admin_password}';\n"
        "CREATE DATABASE IF NOT EXISTS olist_ecommerce CHARACTER SET utf8mb4 "
        "COLLATE utf8mb4_unicode_ci;\n"
        f"CREATE USER 'olist_app'@'127.0.0.1' IDENTIFIED BY '{app_password}';\n"
        "GRANT ALL PRIVILEGES ON olist_ecommerce.* TO 'olist_app'@'127.0.0.1';\n",
        encoding='utf-8'
    )
    with (MYSQL / 'initialize.log').open('w', encoding='utf-8') as log:
        subprocess.run(
            [str(server), f'--defaults-file={ini}', '--initialize-insecure'],
            stdout=log, stderr=subprocess.STDOUT, check=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
    subprocess.run(
        ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
         str(ROOT / 'scripts' / 'start_mysql.ps1'), '-InitFile', str(init_sql)],
        check=True
    )
    # Confirm the init file executed before saving the application config.
    import pymysql
    config = dict(user='olist_app', password=app_password, host='127.0.0.1',
                  port=3307, database='olist_ecommerce', charset='utf8mb4')
    with pymysql.connect(**config) as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT DATABASE()')
            assert cursor.fetchone()[0] == 'olist_ecommerce'
    config_path.write_text('DB_CONFIG = ' + repr(config) + '\n', encoding='utf-8')
    init_sql.unlink()
    print('Local MySQL configured; credentials saved in ignored local files.')


if __name__ == '__main__':
    main()
