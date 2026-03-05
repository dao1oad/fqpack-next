# -*- coding:utf-8 -*-

from pytdx.reader import BlockReader

from freshquant.data.index import fqDataIndexFetchDay, fqDataQAFetchIndexListAdv

# 超级赛道


def run():
    indexList = fqDataQAFetchIndexListAdv()
    print(indexList)
    BlockReader().get_df()


if __name__ == "__main__":
    run()
