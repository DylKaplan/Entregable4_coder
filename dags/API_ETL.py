from psycopg2.extras import execute_values
from datetime import timedelta, datetime
from pathlib import Path
import json
import requests
import psycopg2
from airflow import DAG
from sqlalchemy import create_engine

from email import message
import smtplib

# Operadores
from airflow.operators.python_operator import PythonOperator
# from airflow.utils.dates import days_ago
import pandas as pd
import os

import base64
import io

dag_path = os.getcwd()  # path original.. home en Docker

url = "data-engineer-cluster.cyhh5bfevlmn.us-east-1.redshift.amazonaws"
with open(dag_path+'/keys/'+"db.txt", 'r') as f:
    data_base = f.read()
with open(dag_path+'/keys/'+"user.txt", 'r') as f:
    user = f.read()
with open(dag_path+'/keys/'+"pwd.txt", 'r') as f:
    pwd = f.read()

redshift_conn = {
    'host': url,
    'username': user,
    'database': data_base,
    'port': '5439',
    'pwd': pwd
}

# argumentos por defecto para el DAG
default_args = {
    'owner': 'DylanKaplan',
    'start_date': datetime(2023, 6, 14),
    'retries': 5,
    'retry_delay': timedelta(minutes=5)
}

BC_dag = DAG(
    dag_id='API_ETL',
    default_args=default_args,
    description='Extra data de Google Trends',
    schedule_interval="@daily",
    catchup=False
)

dag_path = os.getcwd()  # path original.. home en Docker


# funcion de extraccion de datos desde git
def extraer_data(exec_date):
    try:
        print(f"Adquiriendo data para la fecha: {exec_date}")
        date = datetime.strptime(exec_date, '%Y-%m-%d %H')

        url = 'https://api.github.com/repos/DylKaplan/data_pytrends/contents/data_pytrends.csv'
        response = requests.get(url)

        file_content = response.json()['content']
        decoded_content = base64.b64decode(file_content)

        iot_from_git = pd.read_csv(
            io.StringIO(decoded_content.decode('utf-8')))

        iot_from_git.to_csv(dag_path+'/processed_data/'+"data_"+str(date.year)+'-'+str(
            date.month)+'-'+str(date.day)+'-'+str(date.hour)+".csv", index=False, mode='a')

    except ValueError as e:
        print("Formato datetime deberia ser %Y-%m-%d %H", e)
        raise e


def enviar(exec_date):
    date = datetime.strptime(exec_date, '%Y-%m-%d %H')
    dataframe = pd.read_csv(dag_path+'/processed_data/'+"data_"+str(date.year)+'-'+str(
        date.month)+'-'+str(date.day)+'-'+str(date.hour)+".csv")

    if 17 in dataframe['Vino']:
        try:
            print(f"Enviando mail. Fecha: {exec_date}")
            x = smtplib.SMTP('smtp.gmail.com', 587)
            x.starttls()
            x.login('dylukaplan@gmail.com', 'toigtctlgtgvrrpb')
            subject = 'Alerta automatica'
            body_text = 'Hay valores altos en la busqueda de vino.'
            message = 'Subject: {}\n\n{}'.format(subject, body_text)
            x.sendmail('dylukaplan@gmail.com', 'dylukaplan@gmail.com', message)
            print('Exito')
        except Exception as exception:
            print(exception)
            print('Failure')

    else:
        print('No se envía mail')


# Funcion conexion a redshift
def conexion_redshift(exec_date):
    print(f"Conectandose a la BD en la fecha: {exec_date}")
    url = "data-engineer-cluster.cyhh5bfevlmn.us-east-1.redshift.amazonaws.com"
    try:
        conn = psycopg2.connect(
            host=url,
            dbname=redshift_conn["database"],
            user=redshift_conn["username"],
            password=redshift_conn["pwd"],
            port='5439')
        print(conn)
        print("Connected to Redshift successfully!")
    except Exception as e:
        print("Unable to connect to Redshift.")
        print(e)
    # engine = create_engine(f'redshift+psycopg2://{redshift_conn["username"]}:{redshift_conn["pwd"]}@{redshift_conn["host"]}:{redshift_conn["port"]}/{redshift_conn["database"]}')
    # print(engine)


# Funcion de envio de data


def cargar_data(exec_date):
    print(f"Cargando la data para la fecha: {exec_date}")
    date = datetime.strptime(exec_date, '%Y-%m-%d %H')
    table_name = 'iot_from_git'
    dataframe = pd.read_csv(dag_path+'/processed_data/'+"data_"+str(date.year)+'-'+str(
        date.month)+'-'+str(date.day)+'-'+str(date.hour)+".csv")
    # date = datetime.strptime(exec_date, '%Y-%m-%d %H')

    # conexion a database
    url = "data-engineer-cluster.cyhh5bfevlmn.us-east-1.redshift.amazonaws.com"
    conn = psycopg2.connect(
        host=url,
        dbname=redshift_conn["database"],
        user=redshift_conn["username"],
        password=redshift_conn["pwd"],
        port='5439')
    dtypes = dataframe.dtypes
    cols = list(dtypes.index)
    tipos = list(dtypes.values)
    type_map = {'int64': 'INT', 'int32': 'INT', 'float64': 'FLOAT',
                'object': 'VARCHAR(150)', 'bool': 'BOOLEAN'}
    sql_dtypes = [type_map[str(dtype)] for dtype in tipos]
    # Definir formato SQL VARIABLE TIPO_DATO
    column_defs = [f"{name} {data_type}" for name,
                   data_type in zip(cols, sql_dtypes)]
    # Combine column definitions into the CREATE TABLE statement
    table_schema = f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            {', '.join(column_defs)}
        );
        """
    # Crear la tabla
    cur = conn.cursor()
    cur.execute(table_schema)
    # Generar los valores a insertar
    values = [tuple(x) for x in dataframe.to_numpy()]
    # Definir el INSERT
    insert_sql = f"INSERT INTO {table_name} ({', '.join(cols)}) VALUES %s"
    # Execute the transaction to insert the data
    cur.execute("BEGIN")
    execute_values(cur, insert_sql, values)
    cur.execute("COMMIT")
    # records.to_sql('mining_data', engine, index=False, if_exists='append')


# Tareas
# 1. Extraccion
task_1 = PythonOperator(
    task_id='extraer_data',
    python_callable=extraer_data,
    op_args=["{{ ds }} {{ execution_date.hour }}"],
    dag=BC_dag,
)

# 2. Envio mail
task_2 = PythonOperator(
    task_id='email',
    python_callable=enviar,
    op_args=["{{ ds }} {{ execution_date.hour }}"],
    dag=BC_dag,
)

# 3. Envio de data
# 3.1 Conexion a base de datos
task_31 = PythonOperator(
    task_id="conexion_BD",
    python_callable=conexion_redshift,
    op_args=["{{ ds }} {{ execution_date.hour }}"],
    dag=BC_dag
)

# 3.2 Envio final
task_32 = PythonOperator(
    task_id='cargar_data',
    python_callable=cargar_data,
    op_args=["{{ ds }} {{ execution_date.hour }}"],
    dag=BC_dag,
)


# Definicion orden de tareas
task_1 >> task_2 >> task_31 >> task_32
