import uuid
import pandas as pd
import boto3
import gzip
from io import BytesIO


def transform_to_parquet(file_name, bucket_name, tgt_folder):
    print(f'Creating JSON Reader for {file_name}')
    
    # Download file from S3 using boto3
    s3_client = boto3.client('s3')
    s3_key = f'landing/ghactivity/{file_name}'
    
    response = s3_client.get_object(Bucket=bucket_name, Key=s3_key)
    gzip_content = response['Body'].read()
    
    # Decompress gzip content
    with gzip.GzipFile(fileobj=BytesIO(gzip_content)) as f:
        json_content = f.read().decode('utf-8')
    
    df_reader = pd.read_json(
        BytesIO(json_content.encode('utf-8')),
        lines=True,
        orient='records',
        chunksize=10000
    )
    year = file_name.split('-')[0]
    month = file_name.split('-')[1]
    dayofmonth = file_name.split('-')[2]
    hour = file_name.split('-')[3].split('.')[0]
    print(f'Transforming JSON to Parquet for {file_name}')
    for idx, df in enumerate(df_reader):
        target_file_name = f'part-{year}-{month}-{dayofmonth}-{hour}-{uuid.uuid1()}.snappy.parquet'
        print(f'Processing chunk {idx} of size {df.shape[0]} from {file_name}')
        
        # Convert DataFrame to parquet and upload to S3
        parquet_buffer = BytesIO()
        df.drop(columns=['payload']).to_parquet(parquet_buffer, index=False)
        parquet_buffer.seek(0)
        
        target_key = f'{tgt_folder}/year={year}/month={month}/dayofmonth={dayofmonth}/{target_file_name}'
        s3_client.put_object(Bucket=bucket_name, Key=target_key, Body=parquet_buffer.getvalue())

    return {
        'last_run_src_file_name': file_name,
        'last_run_tgt_file_pattern': f's3://{bucket_name}/{tgt_folder}/year={year}/month={month}/dayofmonth={dayofmonth}/part-{year}-{month}-{dayofmonth}-{hour}',
        'status_code': 200
    }