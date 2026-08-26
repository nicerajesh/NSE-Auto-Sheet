import pandas as pd
from repair_sheet_output import clean_numeric


def test_target_prices_remain_numeric():
    df=pd.DataFrame({'TARGET_1':['1301.78'],'TARGET_2':['1347.67'],'TARGET_3':['1416.51']})
    out=clean_numeric(df,['TARGET_1','TARGET_2','TARGET_3'])
    assert out['TARGET_1'].iloc[0] == 1301.78
    assert out['TARGET_2'].iloc[0] == 1347.67
    assert out['TARGET_3'].iloc[0] == 1416.51


def test_duplicate_rs_columns_are_not_expected():
    cols=['RS_VS_UNIVERSE']
    assert len([c for c in cols if c.startswith('RS_VS_UNIVERSE')]) == 1
