from pathlib import Path
import pandas as pd
from sqlalchemy import create_engine, text
from urllib.parse import quote_plus

from db_config import DB_CONFIG


def create_mysql_engine():
    user = DB_CONFIG["user"]
    password = quote_plus(DB_CONFIG["password"])
    host = DB_CONFIG["host"]
    port = DB_CONFIG["port"]
    database = DB_CONFIG["database"]
    charset = DB_CONFIG["charset"]

    connection_url = (
        f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}?charset={charset}"
    )

    engine = create_engine(connection_url)
    return engine


def clean_table_name(csv_filename: str) -> str:
    """
    把 CSV 檔名轉成 MySQL table 名稱。

    例：
    olist_customers_dataset.csv -> customers
    olist_orders_dataset.csv -> orders
    """
    table_name = csv_filename.replace(".csv", "")
    table_name = table_name.replace("olist_", "")
    table_name = table_name.replace("_dataset", "")
    return table_name


def get_project_root() -> Path:
    """
    取得專案根目錄。

    __file__ 代表目前這個 .py 檔案的位置。
    假設檔案位置是：
    project/scripts/load_olist_to_mysql.py

    那 parents[1] 就會回到：
    project/
    """
    return Path(__file__).resolve().parents[1]


def check_mysql_connection(engine):
    """
    檢查目前 Python 真的連到哪一個 MySQL database。
    """
    with engine.connect() as conn:
        result = conn.execute(text("SELECT DATABASE();"))
        current_database = result.scalar()

    print(f"目前連線的 database：{current_database}")

    if current_database is None:
        raise RuntimeError("目前沒有連到任何 database，請檢查 DB_CONFIG['database'] 是否正確。")


def show_tables(engine):
    """
    匯入完成後，直接用 Python 查 MySQL 裡有哪些 table。
    """
    with engine.connect() as conn:
        result = conn.execute(text("SHOW TABLES;"))
        tables = result.fetchall()

    print("\n目前 MySQL 裡的 tables：")

    if not tables:
        print("沒有找到任何 table。")
    else:
        for table in tables:
            print("-", table[0])


def load_csv_to_mysql():
    project_root = get_project_root()

    data_path = project_root / "data" / "raw" / "olist"

    print(f"專案根目錄：{project_root}")
    print(f"CSV 資料夾：{data_path}")

    if not data_path.exists():
        raise FileNotFoundError(f"找不到資料夾：{data_path}")

    csv_files = list(data_path.glob("*.csv"))

    print(f"找到 {len(csv_files)} 個 CSV 檔案")

    if not csv_files:
        raise FileNotFoundError(f"資料夾內沒有 CSV 檔案：{data_path}")

    engine = create_mysql_engine()

    check_mysql_connection(engine)

    for file in csv_files:
        table_name = clean_table_name(file.name)

        print(f"\nLoading {file.name} into table `{table_name}`...")

        df = pd.read_csv(file)

        df.to_sql(
            name=table_name,
            con=engine,
            if_exists="replace",
            index=False,
            chunksize=5000
        )

        print(f"Done: {table_name}, shape={df.shape}")

    print("\nAll CSV files loaded into MySQL.")

    show_tables(engine)


if __name__ == "__main__":
    load_csv_to_mysql()