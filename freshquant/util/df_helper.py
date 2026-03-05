import pandas as pd
import numpy as np

def to_dict(df):
    """
    Convert DataFrame to dict with proper null value and datetime handling
    
    Args:
        df: pandas DataFrame
    """
    # Handle datetime columns automatically
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].apply(
                lambda x: x.strftime("%Y-%m-%d %H:%M:%S") if pd.notna(x) else "2099-12-31 23:59:59"
            )
    
    # Convert all null values to None
    df = df.replace({pd.NA: None, pd.NaT: None, np.nan: None})
    
    return df.to_dict("records")