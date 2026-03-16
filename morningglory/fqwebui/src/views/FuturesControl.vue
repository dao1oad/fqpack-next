<template>
  <div class="future-control-shell">
    <MyHeader />
    <div class="future-control-main future-control-body">
    <!--仓位计算-->
    <el-divider content-position="center">仓位计算器</el-divider>
    <el-row>
      <el-form
        :inline="true"
        size="small"
        :model="calcPosForm"
        class="demo-form-inline"
      >
        <el-form-item label="资产总额">
          <el-input v-model="calcPosForm.account" class="form-input " />
        </el-form-item>
        <el-form-item label="保证金系数">
          <el-input
            v-model="calcPosForm.currentMarginRate"
            class="form-input "
            disabled
          />
        </el-form-item>
        <el-form-item label="杠杠倍数">
          <el-input
            v-model="calcPosForm.marginLevel"
            class="form-input "
            disabled
          />
        </el-form-item>
        <el-form-item label="合约乘数">
          <el-input
            v-model="calcPosForm.contractMultiplier"
            class="form-input "
            disabled
          />
        </el-form-item>
        <el-form-item label="开仓价格">
          <el-input v-model="calcPosForm.openPrice" class="form-input" />
        </el-form-item>
        <el-form-item label="止损价格">
          <el-input
            v-model="calcPosForm.stopPrice"
            class="form-input"
            @change="calcAccount"
          />
        </el-form-item>
        <el-form-item label="动止价(选填)">
          <el-input
            v-model="calcPosForm.dynamicWinPrice"
            @change="calcAccount"
            class="form-input"
          />
        </el-form-item>
        <el-form-item label="最大资金使用率">
          <el-select
            v-model="calcPosForm.maxAccountUseRate"
            class="select-input"
          >
            <el-option label="15%" value="0.15" />
            <el-option label="20%" value="0.2" />
            <el-option label="30%" value="0.3" />
          </el-select>
        </el-form-item>
        <el-form-item label="止损系数">
          <el-select v-model="calcPosForm.stopRate" class="select-input">
            <el-option label="0.5%" value="0.005" />
            <el-option label="1%" value="0.01" />
            <el-option label="1.7%" value="0.017" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="calcAccount" class="primary-button"
            >查询</el-button
          >
        </el-form-item>
        <el-form-item label="开仓手数">
          <el-input
            v-model="calcPosForm.maxOrderCount"
            class="form-input "
            disabled
          />
        </el-form-item>
        <el-form-item label="资金使用率">
          <el-input
            v-model="calcPosForm.accountUseRate"
            class="form-input "
            disabled
          />
        </el-form-item>
        <el-form-item label="1手保证金">
          <el-input
            v-model="calcPosForm.perOrderMargin"
            class="form-input "
            disabled
          />
        </el-form-item>
        <el-form-item label="1手止损的金额">
          <el-input
            v-model="calcPosForm.perOrderStopMoney"
            class="form-input "
            disabled
          />
        </el-form-item>
        <el-form-item label="止损百分比">
          <el-input
            v-model="calcPosForm.perOrderStopRate"
            class="form-input "
            disabled
          />
        </el-form-item>
        <el-form-item label="总保证金">
          <el-input
            v-model="calcPosForm.totalOrderMargin"
            class="form-input"
            disabled
          />
        </el-form-item>
        <el-form-item label="总止损额">
          <el-input
            v-model="calcPosForm.totalOrderStopMoney"
            class="form-input"
            disabled
          />
        </el-form-item>
        <el-form-item label="动止手数">
          <el-input
            v-model="calcPosForm.dynamicWinCount"
            class="form-input"
            disabled
          />
        </el-form-item>
      </el-form>
    </el-row>
    <!--持仓区域-->
    <el-divider content-position="center">持仓列表</el-divider>
    <FuturePositionList
      :futureSymbolList="futureSymbolList"
      :futureSymbolMap="futureSymbolMap"
      :marginLevelCompany="marginLevelCompany"
      :globalFutureSymbol="globalFutureSymbol"
    ></FuturePositionList>
    <el-divider content-position="center"> 多空分布</el-divider>
    <el-row type="flex" justify="space-around">
      <el-col :span="4" v-for="(item, i) in 5" :key="i">
        <el-divider content-position="center">
          <span v-if="i === 0">
            有色板块
          </span>
          <span v-else-if="i === 1">
            黑色板块
          </span>
          <span v-else-if="i === 2">
            原油板块
          </span>
          <span v-else-if="i === 3">
            化工板块
          </span>
          <span v-else-if="i === 4">
            油脂板块
          </span>
        </el-divider>
        <el-row class="mt-5">
          <el-col :span="6">
            走势多空(确立)：
          </el-col>
          <el-col :span="18">
            <el-progress
              :percentage="directionPercentage[i]"
              :color="customColorMethod"
              :text-inside="true"
              :stroke-width="24"
            ></el-progress>
          </el-col>
        </el-row>
        <el-row class="mt-5">
          <el-col :span="6">
            信号多空(预期)：
          </el-col>
          <el-col :span="18">
            <el-progress
              :percentage="signalPercentage[i]"
              :color="customColorMethod"
              :text-inside="true"
              :stroke-width="24"
            ></el-progress>
          </el-col>
        </el-row>
        <el-row class="mt-5" :key="forceRefreshPercentage">
          <el-col :span="6">
            涨跌幅：
          </el-col>
          <el-col :span="18">
            <el-progress
              :percentage="changePercentage[i]"
              :color="customColorMethod"
              :text-inside="true"
              :stroke-width="24"
            ></el-progress>
          </el-col>
        </el-row>
      </el-col>
    </el-row>

    <!--        <el-row class="mt-5">-->
    <!--            <el-col :span="2">-->
    <!--                外盘涨跌幅：-->
    <!--            </el-col>-->
    <!--            <el-col :span="22">-->
    <!--                <el-progress-->
    <!--                    :percentage="globalFuturePercentage"-->
    <!--                    :color="customColorMethod"-->
    <!--                    :text-inside="true"-->
    <!--                    :stroke-width="24"-->
    <!--                ></el-progress>-->
    <!--            </el-col>-->
    <!--        </el-row>-->
    <!--        <el-row class="mt-5">-->
    <!--            <el-col :span="2">-->
    <!--                外盘信号多空：-->
    <!--            </el-col>-->
    <!--            <el-col :span="22">-->
    <!--                <el-progress-->
    <!--                    :percentage="globalSignalPercentage"-->
    <!--                    :color="customColorMethod"-->
    <!--                    :text-inside="true"-->
    <!--                    :stroke-width="24"-->
    <!--                ></el-progress>-->
    <!--            </el-col>-->
    <!--        </el-row>-->
    <el-tabs v-model="activeTab" @tab-click="handleChangeTab" class="mt-5">
      <el-tab-pane label="最新行情" name="first">
        <el-row>
          <div class="current-market">
            <el-table
              :v-loading="false"
              :data="
                futureSymbolList.filter(
                  data =>
                    !symbolSearch ||
                    data.order_book_id
                      .toLowerCase()
                      .includes(symbolSearch.toLowerCase())
                )
              "
              size="small"
              header-cell-class-name="el-header-cell"
              cell-class-name="el-cell"
            >
              <el-table-column align="left">
                <template #header="scope">
                  <el-input
                    v-model="symbolSearch"
                    size="small"
                    placeholder="搜索"
                  >
                    <!--                                <el-button type="primary" @click="getSignalList" size="small" slot="append">刷新-->
                    <!--                                </el-button>-->
                  </el-input>
                </template>
                <template #default="scope">
                  <el-link
                    class="primary-color"
                    :underline="false"
                    @click="jumpToKline(scope.row.order_book_id)"
                    >{{ scope.row.order_book_id }}
                  </el-link>
                </template>
              </el-table-column>
              <el-table-column label="名称">
                <template #default="scope">{{ scope.row.name }}</template>
              </el-table-column>
              <el-table-column label="保证金率">
                <template #default="scope">
                  <el-link
                    @click="
                      fillMarginRate(
                        scope.row,
                        changeList && changeList[scope.row.order_book_id]
                          ? changeList[scope.row.order_book_id]['price']
                          : 0
                      )
                    "
                    :underline="false"
                    v-if="scope.row.order_book_id.indexOf('BTC') === -1"
                    >{{
                      (scope.row.margin_rate + marginLevelCompany).toFixed(3)
                    }}
                  </el-link>
                  <el-link
                    @click="fillMarginRate(scope.row, btcTicker.price)"
                    :underline="false"
                    v-else
                    >{{ scope.row.margin_rate.toFixed(3) }}
                  </el-link>
                </template>
              </el-table-column>
              <el-table-column label="涨跌幅">
                <template #default="scope">
                  <!--                                    <el-tag-->
                  <!--                                        effect="dark"-->
                  <!--                                        :type="changeList && changeList[scope.row.order_book_id]? changeList[scope.row.order_book_id]['change'] : 0|changeTagFilter"-->
                  <!--                                        v-if="scope.row.order_book_id.indexOf('BTC')===-1"-->
                  <!--                                    >-->
                  <!--                                        {{ ((changeList && changeList[scope.row.order_book_id]?-->
                  <!--                                        changeList[scope.row.order_book_id]['change'] : 0) * (1 /( scope.row.margin_rate-->
                  <!--                                        +marginLevelCompany)) *100).toFixed(1)}}%-->
                  <!--                                    </el-tag>-->
                  <!--                                    <el-tag-->
                  <!--                                        effect="dark"-->
                  <!--                                        :type="btcTicker.change|changeTagFilter"-->
                  <!--                                        v-else-->
                  <!--                                    >-->
                  <!--                                        {{ ((btcTicker.change?btcTicker.change:0) * (1 /scope.row.margin_rate)-->
                  <!--                                        *100).toFixed(1)}}%-->
                  <!--                                    </el-tag>-->

                  <span
                    :class="
                      changeList && changeList[scope.row.order_book_id]
                        ? changeList[scope.row.order_book_id]['change']
                        : 0 | changeTagFilter
                    "
                    v-if="scope.row.order_book_id.indexOf('BTC') === -1"
                  >
                    {{
                      (
                        (changeList && changeList[scope.row.order_book_id]
                          ? changeList[scope.row.order_book_id]['change']
                          : 0) *
                        (1 / (scope.row.margin_rate + marginLevelCompany)) *
                        100
                      ).toFixed(1)
                    }}%
                  </span>
                  <span
                    v-else
                    :class="btcTicker.change > 0 ? 'up-red' : 'down-green'"
                  >
                    {{
                      (
                        (btcTicker.change ? btcTicker.change : 0) *
                        (1 / scope.row.margin_rate) *
                        100
                      ).toFixed(1)
                    }}%
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="最新价">
                <template #default="scope">
                  <span v-if="scope.row.order_book_id.indexOf('BTC') === -1">
                    {{
                      changeList && changeList[scope.row.order_book_id]
                        ? changeList[scope.row.order_book_id]['price']
                        : 0
                    }}
                  </span>
                  <span v-else>
                    {{ btcTicker.price }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="日20均线" align="center">
                <template #default="scope">
                  <!--                                    <el-tag-->
                  <!--                                        size="medium"-->
                  <!--                                        :type="levelDirectionList&&levelDirectionList[scope.row.order_book_id]?-->
                  <!--                            levelDirectionList[scope.row.order_book_id]['3m']==='多'?'danger':'primary'-->
                  <!--                            :'info'"-->
                  <!--                                    >{{-->
                  <!--                                        levelDirectionList&&levelDirectionList[scope.row.order_book_id]?levelDirectionList[scope.row.order_book_id]['3m']:''-->
                  <!--                                        }}-->
                  <!--                                    </el-tag>-->
                  <!--                                    <el-progress-->
                  <!--                                        :percentage="beichiList[scope.row.order_book_id].hasOwnProperty('percentage')?beichiList[scope.row.order_book_id]['percentage']:0"-->
                  <!--                                        :color="customColorMethod"-->
                  <!--                                        :text-inside="true"-->
                  <!--                                        :stroke-width="24"-->
                  <!--                                        class="mt-5"-->
                  <!--                                    >-->
                  <!--                                    </el-progress>-->
                  <span
                    :class="
                      dayMa20List && dayMa20List[scope.row.order_book_id]
                        ? dayMa20List[scope.row.order_book_id][
                            'above_ma_20'
                          ] === 1
                          ? 'up-red'
                          : 'down-green'
                        : 'zero-gray'
                    "
                  >
                    {{
                      dayMa20List && dayMa20List[scope.row.order_book_id]
                        ? dayMa20List[scope.row.order_book_id][
                            'above_ma_20'
                          ] === 1
                          ? '上'
                          : '下'
                        : '--'
                    }}
                  </span>
                </template>
              </el-table-column>
              <!--                            <el-table-column label="多空力度" align="center">-->
              <!--                                <template #default="scope">-->
              <!--                                    <el-progress-->
              <!--                                        :percentage="beichiList[scope.row.order_book_id]['combine_percentage']"-->
              <!--                                        :color="customColorMethod"-->
              <!--                                        :text-inside="true"-->
              <!--                                        :stroke-width="24"-->
              <!--                                    ></el-progress>-->

              <!--                                </template>-->
              <!--                            </el-table-column>-->
              <!--                            <el-table-column label="1m" align="center">-->
              <!--                                <template #default="scope">-->
              <!--                                    <span-->
              <!--                                        :class="beichiList[scope.row.order_book_id]['1m']&& beichiList[scope.row.order_book_id]['1m']['direction'].indexOf('多')!==-1?'up-red':'down-green'"-->
              <!--                                    >{{ beichiList[scope.row.order_book_id]['1m']['direction'] }}-->
              <!--                                    </span>-->
              <!--                                    <span>-->
              <!--                                     {{ beichiList[scope.row.order_book_id]['1m']['signal'] }}-->
              <!--                                    </span>-->
              <!--                                </template>-->
              <!--                            </el-table-column>-->
              <!--                            <el-table-column label="3m" align="center">-->
              <!--                                <template #default="scope">-->
              <!--                                    <span-->
              <!--                                        :class="beichiList[scope.row.order_book_id]['3m']['direction'].indexOf('多')!==-1?'up-red':'down-green'"-->
              <!--                                    >{{ beichiList[scope.row.order_book_id]['3m']['direction'] }}-->
              <!--                                    </span>-->
              <!--                                    <span>-->
              <!--                                     {{ beichiList[scope.row.order_book_id]['3m']['signal'] }}-->
              <!--                                    </span>-->
              <!--                                </template>-->
              <!--                            </el-table-column>-->

              <!--                            <el-table-column label="5m" align="center">-->
              <!--                                <template #default="scope">-->
              <!--                                    <span-->
              <!--                                        :class="beichiList[scope.row.order_book_id]['5m']['direction'].indexOf('多')!==-1?'up-red':'down-green'"-->
              <!--                                    >{{ beichiList[scope.row.order_book_id]['5m']['direction'] }}-->
              <!--                                    </span>-->
              <!--                                    <span>-->
              <!--                                     {{ beichiList[scope.row.order_book_id]['5m']['signal'] }}-->
              <!--                                    </span>-->
              <!--                                </template>-->
              <!--                            </el-table-column>-->
              <!--               -->
              <!--                            <el-table-column label="15m" align="center">-->
              <!--                                <template #default="scope">-->
              <!--                                    <span-->
              <!--                                        :class="beichiList[scope.row.order_book_id]['15m']['direction'].indexOf('多')!==-1?'up-red':'down-green'"-->
              <!--                                    >{{ beichiList[scope.row.order_book_id]['15m']['direction'] }}-->
              <!--                                    </span>-->
              <!--                                    <span>-->
              <!--                                     {{ beichiList[scope.row.order_book_id]['15m']['signal'] }}-->
              <!--                                    </span>-->
              <!--                                </template>-->
              <!--                            </el-table-column>-->
              <!--            -->
              <!--                            <el-table-column label="30m" align="center">-->
              <!--                                <template #default="scope">-->
              <!--                                    <span-->
              <!--                                        :class="beichiList[scope.row.order_book_id]['30m']['direction'].indexOf('多')!==-1?'up-red':'down-green'"-->
              <!--                                    >{{ beichiList[scope.row.order_book_id]['30m']['direction'] }}-->
              <!--                                    </span>-->
              <!--                                    <span>-->
              <!--                                     {{ beichiList[scope.row.order_book_id]['30m']['signal'] }}-->
              <!--                                    </span>-->
              <!--                                </template>-->
              <!--                            </el-table-column>-->
            </el-table>
          </div>
        </el-row>
      </el-tab-pane>
      <el-tab-pane label="每日复盘" name="second">
        <el-row>
          <div class="prejudge-form">
            <el-date-picker
              v-model="endDate"
              type="date"
              placeholder="选择日期"
              format="yyyy 年 MM 月 dd 日"
              value-format="yyyy-MM-dd"
              size="small"
              @change="changePrejudgeDate"
              class="ml-5 mr-5"
            ></el-date-picker>
            <el-button
              @click="createOrUpdatePrejudgeList('create')"
              type="primary"
              class="primary-button"
              size="small"
              v-if="prejudgeTableStatus === 'current'"
              :loading="btnPrejudgeLoading"
              >新增
            </el-button>
            <el-button
              @click="createOrUpdatePrejudgeList('update')"
              type="danger"
              class="primary-button"
              size="small"
              v-if="prejudgeTableStatus === 'history'"
              :loading="btnPrejudgeLoading"
              >更新
            </el-button>
          </div>

          <div class="current-market mt-5">
            <div>
              <!-- 新增 使用主力合约 -->
              <el-table
                :data="prejudgeFormList"
                v-if="prejudgeTableStatus === 'current'"
                header-cell-class-name="el-header-cell"
                cell-class-name="el-cell"
              >
                <el-table-column label="品种" width="100">
                  <template #default="scope">
                    <el-link
                      class="primary-color"
                      :underline="false"
                      @click="jumpToKline(scope.row.order_book_id)"
                      >{{ scope.row.order_book_id }}
                    </el-link>
                  </template>
                </el-table-column>

                <el-table-column width="80">
                  <el-button
                    @click="createOrUpdatePrejudgeList('create')"
                    type="primary"
                    class="primary-button"
                    size="small"
                    v-if="prejudgeTableStatus === 'current'"
                    :loading="btnPrejudgeLoading"
                    >新增
                  </el-button>
                  <el-button
                    @click="createOrUpdatePrejudgeList('update')"
                    type="danger"
                    class="primary-button"
                    size="small"
                    v-if="prejudgeTableStatus === 'history'"
                    :loading="btnPrejudgeLoading"
                    >更新
                  </el-button>
                </el-table-column>
                <el-table-column label="走势预判多">
                  <template #default="scope">
                    <input
                      type="text"
                      v-model="prejudgeFormLongMap[scope.row.order_book_id]"
                      class="prejudge-input"
                      @keyup.enter="onInputChange"
                    />
                  </template>
                </el-table-column>
                <el-table-column label="走势预判空">
                  <template #default="scope">
                    <input
                      type="text"
                      v-model="prejudgeFormShortMap[scope.row.order_book_id]"
                      class="prejudge-input"
                      @keyup.enter="onInputChange"
                    />
                  </template>
                </el-table-column>
              </el-table>
              <!-- 更新 不一定是主力合约-->
              <el-table
                :data="historyPrejudgeList"
                v-if="prejudgeTableStatus === 'history'"
                header-cell-class-name="el-header-cell"
                cell-class-name="el-cell"
              >
                <el-table-column label="历史品种" width="100">
                  <template #default="scope">
                    <el-link
                      class="primary-color"
                      :underline="false"
                      @click="jumpToKline(scope.row)"
                      >{{ scope.row }}
                    </el-link>
                  </template>
                </el-table-column>
                <el-table-column width="80">
                  <el-button
                    @click="createOrUpdatePrejudgeList('create')"
                    type="primary"
                    class="primary-button"
                    size="small"
                    v-if="prejudgeTableStatus === 'current'"
                    :loading="btnPrejudgeLoading"
                    >新增
                  </el-button>
                  <el-button
                    @click="createOrUpdatePrejudgeList('update')"
                    type="danger"
                    class="primary-button"
                    size="small"
                    v-if="prejudgeTableStatus === 'history'"
                    :loading="btnPrejudgeLoading"
                    >更新
                  </el-button>
                </el-table-column>
                <el-table-column label="历史走势预判">
                  <template #default="scope">
                    <!-- {{historyPrejudgeMap[scope.row]}} -->
                    <input
                      type="text"
                      v-model="historyPrejudgeLongMap[scope.row]"
                      class="prejudge-input"
                      @keyup.enter="onInputChange"
                    />
                  </template>
                </el-table-column>
                <el-table-column label="历史走势预判">
                  <template #default="scope">
                    <!-- {{historyPrejudgeMap[scope.row]}} -->
                    <input
                      type="text"
                      v-model="historyPrejudgeShortMap[scope.row]"
                      class="prejudge-input"
                      @keyup.enter="onInputChange"
                    />
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </div>
        </el-row>
      </el-tab-pane>
      <el-tab-pane label="统计数据" name="third">
        <StatisticsChat></StatisticsChat>
      </el-tab-pane>
    </el-tabs>
    </div>
  </div>
</template>

<script>
import futureControl from "./js/future-control.js"
export default futureControl
</script>

<style lang="stylus">
@import '../style/futures-control.styl';
</style>
