import unittest
from unittest.mock import patch, MagicMock
import pandas as pd
from freshquant.assets.stock_board_concept_name_em import (
    fetch_stock_board_concept_name_em,
    clean_stock_board_concept_name_em
)

class TestStockBoardConceptNameEm(unittest.TestCase):

    @patch('akshare.stock_board_concept_name_em')
    @patch('freshquant.database.mongodb.DBfreshquant.stock_board_concept_name_em')
    def test_fetch_stock_board_concept_name_em(self, mock_db, mock_ak):
        # 模拟akshare返回的数据
        mock_data = pd.DataFrame({
            '排名': [1],
            '板块名称': ['测试板块'],
            '板块代码': ['test_code'],
            '最新价': [10.0],
            '涨跌额': [0.5],
            '涨跌幅': [5.0],
            '总市值': [1000000],
            '换手率': [1.5],
            '上涨家数': [10],
            '下跌家数': [2],
            '领涨股票': ['测试股票'],
            '领涨股票-涨跌幅': [5.0]
        })
        mock_ak.return_value = mock_data
        
        # 模拟MongoDB操作
        mock_db.bulk_write.return_value = MagicMock()
        
        # 执行测试
        result = fetch_stock_board_concept_name_em()
        
        # 验证返回结果
        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]['board_name'], '测试板块')
        
        # 验证MongoDB操作
        mock_db.bulk_write.assert_called_once()

    @patch('freshquant.database.mongodb.DBfreshquant.stock_board_concept_name_em')
    def test_clean_stock_board_concept_name_em(self, mock_db):
        # 模拟删除操作
        mock_db.delete_many.return_value = MagicMock(deleted_count=10)
        
        # 执行测试
        result = clean_stock_board_concept_name_em()
        
        # 验证返回结果
        self.assertEqual(result, 10)
        
        # 验证MongoDB操作
        mock_db.delete_many.assert_called_once()

if __name__ == '__main__':
    unittest.main()