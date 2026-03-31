<template>
  <div class="position-list-main">
    <!--持仓查询-->
    <el-form :inline="true" :model="positionQueryForm" size="small">
      <el-form-item label="持仓状态">
        <el-select
          v-model="positionQueryForm.status"
          class="form-input-short"
          placeholder="请选择"
          @change="handleQueryStatusChange"
        >
          <el-option key="all" value="all" label="全部" />
          <el-option
            v-for="item in statusOptions"
            :key="item.key"
            :label="item.display_name"
            :value="item.key"
          />
        </el-select>
        <el-date-picker
          v-model="endDate"
          type="date"
          placeholder="选择日期"
          format="yyyy 年 MM 月 dd 日"
          value-format="yyyy-MM-dd"
          size="small"
          @change="getPositionList()"
          class="ml-5 mr-5"
        >
        </el-date-picker>
        <el-button
          type="primary"
          @click="quickSwitchDay('pre')"
          size="small"
          class="primary-button"
          >前一天</el-button
        >
        <el-button
          type="primary"
          @click="quickSwitchDay('next')"
          size="small"
          class="primary-button"
          >后一天</el-button
        >
      </el-form-item>
      <!--      <el-form-item>-->
      <!--        <el-button-->
      <!--          type="primary"-->
      <!--          @click="handleCreatePos"-->
      <!--          size="small"-->
      <!--          class="query-position-form"-->
      <!--        >新增持仓</el-button>-->
      <!--      </el-form-item>-->
    </el-form>
    <!--        持仓对话框-->
    <el-dialog
      :title="textMap[dialogStatus]"
      v-model:visible="dialogFormVisible"
      :fullscreen="true"
    >
      <el-form
        ref="positionFormRef"
        :rules="rules"
        :model="positionForm"
        label-position="left"
        label-width="80px"
        size="small"
        :inline="true"
      >
        <el-row>
          <el-col :span="6">
            <el-form-item label="品种" prop="symbol">
              <el-select
                v-model="positionForm.symbol"
                class="form-input"
                placeholder="请选择"
                filterable
              >
                <el-option
                  v-for="item in futureSymbolList"
                  :key="item.order_book_id"
                  :label="item.order_book_id"
                  :value="item.order_book_id"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="入场信号" prop="signal">
              <el-select
                v-model="positionForm.signal"
                class="form-input"
                placeholder="请选择"
              >
                <el-option
                  v-for="item in signalTypeOptions"
                  :key="item.key"
                  :label="item.display_name"
                  :value="item.key"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="方向" prop="direction">
              <el-select
                v-model="positionForm.direction"
                class="form-input"
                placeholder="请选择"
              >
                <el-option
                  v-for="item in directionOptions"
                  :key="item.key"
                  :label="item.display_name"
                  :value="item.key"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="周期图" prop="period">
              <el-select
                v-model="positionForm.period"
                class="form-input"
                placeholder="请选择"
              >
                <el-option
                  v-for="item in periodOptions"
                  :key="item.key"
                  :label="item.display_name"
                  :value="item.key"
                />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row>
          <el-col :span="6">
            <el-form-item label="入场时间">
              <el-date-picker
                v-model="positionForm.enterTime"
                type="datetime"
                placeholder="选择时间"
                class="form-input"
              />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="入场价格" prop="price">
              <el-input
                v-model.number="positionForm.price"
                type="number"
                placeholder="请输入"
                class="form-input"
              />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="数量" prop="amount">
              <el-input
                v-model.number="positionForm.amount"
                type="number"
                placeholder="请输入"
                class="form-input"
              />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row>
          <el-col :span="6">
            <el-form-item label="状态" prop="status">
              <el-select
                v-model="positionForm.status"
                class="form-input"
                placeholder="请选择"
              >
                <el-option
                  v-for="item in statusOptions"
                  :key="item.key"
                  :label="item.display_name"
                  :value="item.key"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="止损价格" prop="price">
              <el-input
                v-model.number="positionForm.stopLosePrice"
                type="number"
                placeholder="请输入"
                class="form-input"
              />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="入场逻辑">
              <el-input
                v-model="positionForm.enterReason"
                :autosize="{ minRows: 4, maxRows: 4 }"
                type="textarea"
                class="form-textarea-middle"
                placeholder="请输入"
              />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row>
          <el-col :span="18">
            <el-form-item label="持仓逻辑">
              <el-input
                v-model="positionForm.holdReason"
                :autosize="{ minRows: 4, maxRows: 4 }"
                type="textarea"
                class="form-textarea-long"
                placeholder="请输入"
              />
            </el-form-item>
          </el-col>
        </el-row>

        <!-- 动态止盈start -->
        <!--    编辑状态-->
        <el-divider content-position="left"
          >持仓过程记录（ 动态止盈 | 加仓 | 锁仓 | 止损 ）</el-divider
        >
        <el-row
          v-for="(dynamicPosition, index) in positionForm.dynamicPositionList"
          :key="index"
        >
          <el-col :span="5">
            <el-form-item label="时间">
              <el-date-picker
                v-model="dynamicPosition.time"
                type="datetime"
                placeholder="选择时间"
                class="form-input"
              />
            </el-form-item>
          </el-col>
          <el-col :span="4">
            <el-form-item label="价格">
              <el-input
                v-model="dynamicPosition.price"
                type="number"
                placeholder="输入价格"
                class="form-input-short"
              />
            </el-form-item>
          </el-col>
          <el-col :span="4">
            <el-form-item label="数量">
              <el-input
                v-model="dynamicPosition.amount"
                type="number"
                placeholder="输入数量"
                class="form-input-short"
              />
            </el-form-item>
          </el-col>
          <el-col :span="3">
            <el-form-item label="方向" prop="direction">
              <el-select
                v-model="dynamicPosition.direction"
                class="form-input-short"
                placeholder="请选择"
              >
                <el-option
                  v-for="item in dynamicDirectionOptions"
                  :key="item.key"
                  :label="item.display_name"
                  :value="item.key"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="7">
            <el-form-item label="原因">
              <el-input
                v-model="dynamicPosition.reason"
                :autosize="{ minRows: 2, maxRows: 4 }"
                type="textarea"
                class="long-textarea"
                placeholder="请输入"
              />
            </el-form-item>
          </el-col>
          <el-col :span="1">
            <el-button
              @click.prevent="removeDynamicPosition(index)"
              size="small"
              type="danger"
              icon="el-icon-delete"
              >删除
            </el-button>
          </el-col>
        </el-row>
        <el-button @click="addDynamicPosition" size="small" type="success"
          >新增持仓操作</el-button
        >
      </el-form>
      <template #footer>
        <div class="dialog-footer">
          <el-button @click="dialogFormVisible = false" size="small"
            >取消</el-button
          >
          <el-button
            type="primary"
            @click="dialogStatus === 'create' ? createData() : updateData()"
            size="small"
            :loading="submitBtnLoading"
            >确定
          </el-button>
        </div>
      </template>
    </el-dialog>
    <!--        持仓列表-->
    <el-table
      :data="positionList"
      fit
      style="width: 100%;"
      size="small"
      :row-class-name="tableRowClassName"
      :row-key="getRowKeys"
      :row-style="tableRowStyle"
      header-cell-class-name="el-header-cell"
      cell-class-name="el-cell"
      show-summary
      :summary-method="getSummaries"
    >
      <!--            :default-sort="{prop: 'current_profit', order: 'ascending'}"-->
      <!--                        show-summary
            -->

      <el-table-column type="expand" label="展开">
        <template #default="{row}">
          <el-table
            v-if="Object.hasOwnProperty(row, 'dynamicPositionList')"
            :data="row.dynamicPositionList"
            fit
            size="small"
            header-cell-class-name="el-header-cell"
            cell-class-name="el-cell"
          >
            <el-table-column label="动止时间" align="center">
              <template #default="{row}">
                <span>{{
                  parseTime(row.date_created, '{y}-{m}-{d} {h}:{i}')
                }}</span>
              </template>
            </el-table-column>
            <el-table-column
              label="动止价格"
              prop="stop_win_price"
              align="center"
            />
            <el-table-column
              label="动止数量"
              prop="stop_win_count"
              align="center"
            />
            <el-table-column
              label="动止盈利"
              prop="stop_win_money"
              align="center"
            />
            <el-table-column
              label="分型价格"
              prop="fractal_price"
              align="center"
            />
            <el-table-column
              label="大级别"
              prop="fractal_period"
              align="center"
            />
            <el-table-column label="滑点" prop="direction" align="center">
              <template #default="{row}">
                <span>{{
                  Math.abs(row.stop_win_price - row.fractal_price).toFixed(1)
                }}</span>
              </template>
            </el-table-column>
            <el-table-column label="动止方向" prop="direction" align="center">
              <template #default="{row}">
                <span :class="directionTagFilter(row.direction)">
                  <span>{{ directionFilter(row.direction) }}</span>
                </span>
              </template>
            </el-table-column>
          </el-table>
        </template>
      </el-table-column>
      <el-table-column label="操作状态" align="center" :key="0" width="105">
        <template #default="{row}">
          <el-select
            v-model="row.status"
            size="small"
            @change="changeStatus(row._id, row.status, row.close_price)"
            effect="dark"
          >
            <el-option
              v-for="item in statusOptions"
              :key="item.key"
              :label="item.display_name"
              :value="item.key"
            ></el-option>
          </el-select>
        </template>
      </el-table-column>
      <el-table-column label="品种" prop="symbol" align="left" :key="1">
        <template #default="{row}">
          <el-link
            type="primary"
            underline="never"
            @click="handleJumpToKline(row)"
            v-if="globalFutureSymbol.indexOf(row.symbol) !== -1"
          >
            {{ row.symbol }}
            <span class="up-red">外 </span>
            <span
              v-if="
                row.dynamicPositionList && row.dynamicPositionList.length > 0
              "
              class="down-green"
            >
              动</span
            >
          </el-link>
          <el-link
            type="primary"
            underline="never"
            @click="handleJumpToKline(row)"
            v-else
          >
            {{ row.symbol }}
            <span
              v-if="
                row.dynamicPositionList && row.dynamicPositionList.length > 0
              "
              class="down-green"
            >
              动</span
            >
          </el-link>
          <!-- todo                      @click="handleJumpToKline(row)"-->
        </template>
      </el-table-column>
      <el-table-column label="方向" prop="direction" align="center" :key="5">
        <template #default="{row}">
          <span :class="directionTagFilter(row.direction)">
            <span>{{ directionFilter(row.direction) }}</span>
          </span>
        </template>
      </el-table-column>
      <el-table-column label="周期" prop="period" align="center" :key="2" />
      <el-table-column label="入场时间" align="center" :key="3" width="135">
        <template #default="{row}">
          <span>{{ row.date_created }}</span>
        </template>
      </el-table-column>

      <el-table-column
        label="止盈时间"
        align="center"
        :key="29"
        v-if="positionQueryForm.status === 'winEnd'"
        width="135"
      >
        <template #default="{row}">
          <span>{{ row.win_end_time }}</span>
        </template>
      </el-table-column>
      <el-table-column
        label="止损时间"
        align="center"
        :key="30"
        v-if="positionQueryForm.status === 'loseEnd'"
        width="135"
      >
        <template #default="{row}">
          <span>{{ row.lose_end_time }}</span>
        </template>
      </el-table-column>

      <el-table-column label="信号" align="center" :key="4">
        <template #default="{row}">
          <span :class="row.signal === 'tupo' ? 'down-green' : 'up-red'">{{
            signalTypeFilter(row.signal)
          }}</span>
        </template>
      </el-table-column>
      <el-table-column label="分类" align="center" :key="28">
        <template #default="{row}">
          <span>{{ row.tag }}</span>
        </template>
      </el-table-column>
      <el-table-column label="MA5" prop="above_ma5" align="center" :key="31">
        <template #default="{row}">
          <span :class="row.above_ma5 === '下' ? 'down-green' : 'up-red'">{{
            row.above_ma5
          }}</span>
        </template>
      </el-table-column>
      <el-table-column label="MA20" prop="above_ma20" align="center" :key="32">
        <template #default="{row}">
          <span :class="row.above_ma20 === '下' ? 'down-green' : 'up-red'">{{
            row.above_ma20
          }}</span>
        </template>
      </el-table-column>
      <el-table-column label="前低" prop="not_lower" align="center" :key="33">
        <template #default="{row}">
          <span :class="row.not_lower === '下' ? 'down-green' : 'up-red'">{{
            row.not_lower
          }}</span>
        </template>
      </el-table-column>
      <el-table-column label="前高" prop="not_higher" align="center" :key="34">
        <template #default="{row}">
          <span :class="row.not_higher === '下' ? 'down-green' : 'up-red'">{{
            row.not_higher
          }}</span>
        </template>
      </el-table-column>

      <el-table-column label="分型" prop="fractal" align="center" :key="35">
        <template #default="{row}">
          <span :class="row.fractal === '下' ? 'down-green' : 'up-red'">{{
            row.fractal
          }}</span>
        </template>
      </el-table-column>
      <el-table-column label="动力" prop="power" align="center" :key="36">
        <template #default="{row}">
          <span :class="row.power > 50 ? 'primary-yellow' : 'white'">{{
            row.power
          }}</span>
        </template>
      </el-table-column>

      <el-table-column label="成本价" prop="price" align="center" :key="6" />
      <el-table-column label="数量" prop="amount" align="center" :key="7" />
      <!--            后台只更新持仓单的最新价，浮盈率，浮盈额. 老合约没必要继续更新最新价，因此这几个字段都不显示，但是列不能删除
                            删除了会导致表格求和位置要修改-->
      <el-table-column
        label="最新价"
        width="80"
        align="center"
        v-if="positionQueryForm.status === 'holding'"
        :key="8"
      >
        <template #default="{row}">
          {{ Number(row.close_price) }}
        </template>
      </el-table-column>
      <el-table-column
        label="浮盈率"
        align="center"
        prop="current_profit_rate"
        v-if="positionQueryForm.status === 'holding'"
        :key="9"
      >
        <template #default="{row}">
          <span :class="percentTagFilter(row.current_profit_rate)"
            >{{ parseInt(row.current_profit_rate * 100) }}%</span
          >
        </template>
      </el-table-column>

      <el-table-column
        label="浮盈额"
        align="center"
        prop="current_profit"
        v-if="positionQueryForm.status === 'holding'"
        :key="10"
      >
        <template #default="{row}">
          <span :class="percentTagFilter(row.current_profit)">{{
            parseInt(row.current_profit)
          }}</span>
        </template>
      </el-table-column>
      <el-table-column label="保证金" width="80" align="center" :key="11">
        <template #default="{row}">{{ row.total_margin }}</template>
      </el-table-column>
      <el-table-column label="止损价" align="center" :key="12">
        <template #default="{row}">
          <span class="primary-yellow">
            {{ row.stop_lose_price }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="止损率" width="80" align="center" :key="13">
        <template #default="{row}">-{{ calcStopLoseRate(row) }}%</template>
      </el-table-column>
      <el-table-column
        label="止损额"
        prop="predict_stop_money"
        width="110"
        align="center"
        :key="14"
        v-if="positionQueryForm.status !== 'winEnd'"
      >
        <template #default="{row}">
          <span class="down-green">
            {{ row.predict_stop_money }}
          </span>
        </template>
      </el-table-column>
      <el-table-column
        label="实际止损价"
        prop="lose_end_price"
        width="110"
        align="center"
        v-if="positionQueryForm.status === 'loseEnd'"
        :key="15"
      >
        <template #default="{row}">
          {{ row.status === 'loseEnd' ? row.lose_end_price : 0 }}
        </template>
      </el-table-column>
      <el-table-column
        label="实际亏损额"
        width="110"
        align="center"
        v-if="positionQueryForm.status === 'loseEnd'"
        :key="16"
      >
        <template #default="{row}">
          <span class="down-green">
            {{ row.status === 'loseEnd' ? parseInt(row.lose_end_money) : 0 }}
          </span>
        </template>
      </el-table-column>
      <el-table-column
        label="亏损额比率"
        prop="lose_end_rate"
        width="110"
        align="center"
        v-if="positionQueryForm.status === 'loseEnd'"
        :key="17"
      >
        <template #default="{row}">
          {{
            row.status === 'loseEnd'
              ? (row.lose_end_rate * 100).toFixed(0) + '%'
              : 0
          }}
        </template>
      </el-table-column>

      <el-table-column
        label="止盈价"
        width="110"
        align="center"
        v-if="positionQueryForm.status === 'winEnd'"
        :key="18"
      >
        <template #default="{row}">
          {{ row.status === 'winEnd' ? row.win_end_price : 0 }}
        </template>
      </el-table-column>

      <el-table-column
        label="已盈利额"
        width="110"
        align="center"
        v-if="positionQueryForm.status === 'winEnd'"
        :key="19"
      >
        <template #default="{row}">
          <span class="up-red">
            {{ row.status === 'winEnd' ? parseInt(row.win_end_money) : 0 }}
          </span>
        </template>
      </el-table-column>
      <el-table-column
        label="已盈利比率"
        prop="win_end_rate"
        width="110"
        align="center"
        v-if="positionQueryForm.status === 'winEnd'"
        :key="20"
      >
        <template #default="{row}">
          <span class="up-red">
            {{
              row.status === 'winEnd'
                ? (row.win_end_rate * 100).toFixed(0) + '%'
                : 0
            }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="盈亏比" width="80" align="center" :key="21">
        <template #default="{row}">
          <span :class="winLoseRateTagFilter(calcWinLoseRate(row))"
            >{{ calcWinLoseRate(row) }}
          </span>
        </template>
      </el-table-column>
      <!--            <el-table-column label="动止数" prop="stop_win_count" width="90" align="center" :key="22">-->
      <!--                <template #default="{row}">-->
      <!--                    {{row.stop_win_count}}-->
      <!--                </template>-->
      <!--            </el-table-column>-->
      <!--            <el-table-column label="动止价" prop="stop_win_count" width="90" align="center" :key="23">-->
      <!--                <template #default="{row}">-->
      <!--                    {{row.stop_win_price}}-->
      <!--                </template>-->
      <!--            </el-table-column>-->
      <!--            <el-table-column label="动止收益" prop="stop_win_money" width="90" align="center" :key="24">-->
      <!--                <template #default="{row}">-->
      <!--                    {{row.stop_win_money}}-->
      <!--                </template>-->
      <!--            </el-table-column>-->
      <!-- 止盈的时候计算盈利率 -->
      <!--            <el-table-column-->
      <!--                label="盈利率"-->
      <!--                width="100"-->
      <!--                align="center"-->
      <!--            >-->
      <!--&lt;!&ndash;                <template #default="{row}">&ndash;&gt;-->
      <!--&lt;!&ndash;                    <el-tag :type="percentTagFilter(calcWinEndRate(row))">{{ calcWinEndRate(row) }}%</el-tag>&ndash;&gt;-->
      <!--&lt;!&ndash;                </template>&ndash;&gt;-->
      <!--            </el-table-column>-->

      <!--      <el-table-column label="入场逻辑" prop="enterReason" align="center" width="300" />-->
      <!-- <el-table-column label="持仓逻辑" prop="holdReason" align="center" width="300" /> -->
      <el-table-column
        label="最后更新时间"
        prop="last_update_time"
        align="center"
        :key="25"
        width="135"
      />
      <el-table-column
        label="最后信号"
        prop="last_update_signal"
        align="center"
        width="80"
        :key="26"
      />
      <el-table-column
        label="最后周期"
        prop="last_update_period"
        align="center"
        width="80"
        :key="27"
      />

      <!--            <el-table-column label="操作" align="center">-->
      <!--                <template #default="{row,$index}">-->
      <!--                    &lt;!&ndash;          <el-button type="primary" size="small" @click="handleUpdate(row)">编辑</el-button>&ndash;&gt;-->
      <!--                </template>-->
      <!--            </el-table-column>-->
    </el-table>
    <el-pagination
      layout="total,sizes,prev, pager, next"
      v-model:current-page="listQuery.current"
      :page-size="listQuery.size"
      :total="listQuery.total"
      :page-sizes="[10, 50, 100]"
      @current-change="handlePageChange"
      @size-change="handleSizeChange"
      class="mt-5"
    />
    <!--当前收益统计        -->

    <el-row class="mt-10 sum-text">
      <!--            <el-col :span="12">-->
      <!--                外盘期货（$）-->
      <!--                当前盈利：-->
      <!--                <span :class="percentTagFilter(globalSumObj.currentProfitSum)" class="sum-text">{{globalSumObj.currentProfitSum}}</span>-->
      <!--                预计止损：{{(globalSumObj.predictStopSum)}}-->
      <!--                已止盈：{{(globalSumObj.winEndSum)}}-->
      <!--                已止损：{{(globalSumObj.loseEndSum)}}-->
      <!--                保证金：{{(globalSumObj.marginSum)}}-->
      <!--            </el-col>-->

      <el-col :span="24">
        内盘期货(￥)

        <span
          :class="percentTagFilter(sumObj.currentProfitSum)"
          class="sum-text"
          v-if="positionQueryForm.status === 'holding'"
          >当前盈利：{{ sumObj.currentProfitSum + sumObj.winEndSum }} 占比：{{
            sumObj.currentProfitSumRate
          }}
          预计止损：{{ sumObj.predictStopSum }}
        </span>

        <span v-if="positionQueryForm.status === 'winEnd'">
          已止盈：{{ sumObj.winEndSum }} 占比：{{ sumObj.winEndSumRate }}</span
        >
        <span v-if="positionQueryForm.status === 'loseEnd'"
          >已止损：{{ sumObj.loseEndSum }}</span
        >
        保证金：{{ sumObj.marginSum }} 占比：{{ sumObj.marginSumRate }}
      </el-col>
    </el-row>
  </div>
</template>

<script>
import CommonTool from '@/tool/CommonTool'
import { futureApi } from '@/api/futureApi'
import {
  futureAccount,
  globalFutureSymbol as defaultGlobalFutureSymbol
} from '@/config/tradingConstants.mjs'

const signalTypeOptions = [
  { key: 'tupo', display_name: '突破' },
  { key: 'huila', display_name: '拉回' },
  { key: 'break', display_name: '破坏' },
  { key: 'v_reverse', display_name: 'V反' },
  { key: 'beichi', display_name: '背驰' },
  { key: 'five_v_reverse', display_name: '5浪V' },
  { key: 'ma_cross', display_name: '金死叉' }
]
const directionOptions = [
  { key: 'long', display_name: '多' },
  { key: 'short', display_name: '空' }
]
const dynamicDirectionOptions = [
  { key: 'long', display_name: '多' },
  { key: 'short', display_name: '空' },
  { key: 'close', display_name: '平' }
]
const statusOptions = [
  { key: 'holding', display_name: '持仓' },
  // {key: "prepare", display_name: "预埋单"},
  { key: 'winEnd', display_name: '止盈' },
  { key: 'loseEnd', display_name: '止损' },
  { key: 'exception', display_name: '异常' }
]
const periodOptions = [
  { key: '3m', display_name: '3m' },
  { key: '5m', display_name: '5m' },
  { key: '15m', display_name: '15m' },
  { key: '30m', display_name: '30m' },
  { key: '60m', display_name: '60m' },
  { key: '180m', display_name: '180m' }
]
// arr to obj, such as { CN : "China", US : "USA" }
const signalTypeKeyValue = signalTypeOptions.reduce((acc, cur) => {
  acc[cur.key] = cur.display_name
  return acc
}, {})
const directionKeyValue = directionOptions.reduce((acc, cur) => {
  acc[cur.key] = cur.display_name
  return acc
}, {})
export default {
  name: 'PositionList',
  props: {
    futureSymbolList: {
      type: Array,
      default: function () {
        return []
      }
    },
    futureSymbolMap: {
      type: Object,
      default: null
    },
    marginLevelCompany: {
      type: Number,
      default: 0
    },
    globalFutureSymbol: {
      type: Array,
      default: () => [...defaultGlobalFutureSymbol]
    }
  },
  data () {
    return {
      globalSumObj: {
        // 当前盈利
        currentProfitSum: 0,
        // 保证金
        marginSum: 0,
        // 已盈利
        winEndSum: 0,
        // 已止损
        loseEndSum: 0,
        // 预计止损
        predictStopSum: 0
      },
      sumObj: {
        // 当前盈利
        currentProfitSum: 0,
        // 当前盈利占总账户比例
        currentProfitSumRate: 0,
        // 保证金
        marginSum: 0,
        // 已盈利
        winEndSum: 0,
        // 已盈利占总账户比例
        winEndSumRate: 0,

        // 已止损
        loseEndSum: 0,
        // 预计止损
        predictStopSum: 0,
        // 保证金占用总账户比例
        marginSumRate: 0
      },
      endDate: CommonTool.dateFormat('yyyy-MM-dd'),
      futureConfig: {},
      rateColors: ['#99A9BF', '#F7BA2A', '#FF9900'],
      tableKey: 0,
      listLoading: false,
      positionListRefreshTimer: null,
      // 持仓列表
      positionList: [],
      positionQueryForm: {
        status: 'holding'
      },
      // 分页对象
      listQuery: {
        size: 50,
        total: 0,
        current: 1
      },
      // 表单
      positionForm: {
        // importance: 3,
        enterTime: new Date(),
        symbol: '',
        period: '3m',
        signal: '',
        status: 'holding',
        // 方向
        direction: '',
        // 价格
        price: '',
        // 数量
        amount: '',
        stopLosePrice: '',
        // 区间套级别
        // nestLevel: "2级套",
        // 介入逻辑
        enterReason: '',
        // 持仓逻辑
        holdReason: '',
        // 动态止盈,加仓，止损，锁仓列表
        dynamicPositionList: []
      },
      rules: {
        signal: [
          { required: true, message: '请选择入场信号', trigger: 'change' }
        ],
        enterTime: [
          {
            type: 'date',
            required: true,
            message: '请选择入场时间',
            trigger: 'change'
          }
        ],
        symbol: [{ required: true, message: '请选择品种', trigger: 'change' }],
        period: [
          { required: true, message: '请选择周期图', trigger: 'change' }
        ],
        status: [{ required: true, message: '请选择状态', trigger: 'change' }],
        direction: [
          { required: true, message: '请选择方向', trigger: 'change' }
        ],
        price: [{ required: true, message: '请输入价格', trigger: 'blur' }],
        amount: [{ required: true, message: '请输入数量', trigger: 'blur' }]
        // nestLevel: [
        //   { required: true, message: "请选择预期级别", trigger: "change" }
        // ],
        // enterReason: [
        //   { required: true, message: "请输入入场逻辑", trigger: "blur" }
        // ]
      },
      dialogFormVisible: false,
      // 防止重复提交
      submitBtnLoading: false,
      dialogStatus: '',
      textMap: {
        update: '编辑',
        create: '新增'
      },
      statusOptions,
      signalTypeOptions,
      periodOptions,
      directionOptions,
      dynamicDirectionOptions
    }
  },
  mounted () {
    const symbolConfig = window.localStorage.getItem('symbolConfig')
    if (symbolConfig !== null) {
      this.futureConfig = JSON.parse(symbolConfig)
      this.getPositionList()
    }
    // 静默更新合约配置
    this.getFutureConfig()
  },
  beforeUnmount () {
    if (this.positionListRefreshTimer) {
      window.clearInterval(this.positionListRefreshTimer)
      this.positionListRefreshTimer = null
    }
  },
  methods: {
    directionTagFilter (direction) {
      const directionMap = {
        long: 'up-red',
        short: 'down-green'
      }
      return directionMap[direction]
    },
    percentTagFilter (percent) {
      if (percent > 0) {
        return 'up-red'
      } else if (percent < 0) {
        return 'down-green'
      } else {
        return 'zero-gray'
      }
    },
    winLoseRateTagFilter (rate) {
      if (rate >= 1) {
        return 'up-red'
      }
      return 'zero-gray'
    },
    directionFilter (direction) {
      return directionKeyValue[direction]
    },
    signalTypeFilter (type) {
      return signalTypeKeyValue[type]
    },
    parseTime (time, fmt) {
      return CommonTool.parseTime(time, fmt)
    },
    // calcWinEndRate(row) {
    //     // 获取动止列表中的最后一次平仓的价格
    //     if (row.dynamicPositionList.length > 0) {
    //         let winPrice =
    //             row.dynamicPositionList[row.dynamicPositionList.length - 1].price;
    //         let marginLevel = Number(
    //             (1 / (row.margin_rate + this.marginLevelCompany)).toFixed(2)
    //         );
    //         return Math.abs(
    //             ((winPrice - row.price) / row.price) * 100 * marginLevel
    //         ).toFixed(2);
    //     }
    // },
    quickSwitchDay (type) {
      const tempDate = this.endDate.replace(/-/g, '/')
      const date = new Date(tempDate)
      const preDay = date.getTime() - 3600 * 1000 * 24
      const nextDay = date.getTime() + 3600 * 1000 * 24
      if (type === 'pre') {
        this.endDate = CommonTool.parseTime(preDay, '{y}-{m}-{d}')
      } else {
        this.endDate = CommonTool.parseTime(nextDay, '{y}-{m}-{d}')
      }
      this.getPositionList()
    },
    getFutureConfig () {
      futureApi
        .getFutureConfig()
        .then(res => {
          this.futureConfig = res
          window.localStorage.setItem(
            'symbolConfig',
            JSON.stringify(this.futureConfig)
          )
          if (this.positionListRefreshTimer) {
            window.clearInterval(this.positionListRefreshTimer)
          }
          this.positionListRefreshTimer = window.setInterval(() => {
            this.getPositionList()
          }, 5000)
        })
        .catch(() => {})
    },
    // 计算盈亏比
    calcWinLoseRate (row) {
      const profitRate = row.current_profit_rate * 100
      const stopLoseRate = this.calcStopLoseRate(row)
      if (profitRate === '获取中' || stopLoseRate === '获取中') {
        return '获取中'
      } else {
        return (profitRate / stopLoseRate).toFixed(1)
      }
    },
    // 计算止损率
    calcStopLoseRate (row) {
      return parseInt(row.per_order_stop_rate * 100)
    },
    // //  计算收益率
    // calcProfitRate(row) {
    //     let marginLevel = 1
    //     if (row.symbol === 'BTC') {
    //         // BTC
    //         marginLevel = 1 / this.futureConfig[row.symbol].margin_rate
    //     } else if (row.symbol.indexOf('sz') !== -1 || row.symbol.indexOf('sh') !== -1) {
    //         marginLevel = 1
    //     } else {
    //         // 期货简单代码   RB
    //         let simpleSymbol = row.symbol.replace(/[0-9]/g, '')
    //         const margin_rate = this.futureConfig[simpleSymbol].margin_rate
    //         let currentMarginRate = margin_rate + this.marginLevelCompany
    //         marginLevel = Number((1 / (currentMarginRate)).toFixed(2))
    //     }
    //     let currentPercent = 0;
    //     if (row.direction === "long") {
    //         currentPercent = (
    //             ((row.close_price - row.price) / row.price) *
    //             100 *
    //             marginLevel
    //         ).toFixed(2);
    //     } else {
    //         currentPercent = (
    //             ((row.price - row.close_price) /
    //                 row.close_price) *
    //             100 *
    //             marginLevel
    //         ).toFixed(2);
    //     }
    //     return currentPercent;
    // },
    changeStatus (id, status, close_price) {
      futureApi
        .updatePositionStatus(id, status, close_price)
        .then(res => {
          if (res.code === 'ok') {
            this.getPositionList()
          }
        })
        .catch(() => {
          this.$notify({
            title: 'Error',
            message: '更新状态失败',
            type: 'error',
            duration: 2500
          })
        })
    },
    getRowKeys (row) {
      return row._id
    },

    // 修改table tr行的背景色
    tableRowStyle ({ row, rowIndex }) {
      return 'background-color: pink'
    },
    // 修改table header的背景色
    tableHeaderColor ({ row, column, rowIndex, columnIndex }) {
      // if (rowIndex === 0) {
      return 'background-color: lightblue;color: #fff;font-weight: 500;'
      // }
    },
    tableRowClassName ({ row, rowIndex }) {
      if (Object.hasOwnProperty(row, 'dynamicPositionList')) {
        return 'success-row'
      }
      return ''
    },
    handleSizeChange (currentSize) {
      this.listQuery.size = currentSize
      this.getPositionList()
    },
    handlePageChange (currentPage) {
      this.listQuery.current = currentPage
      this.getPositionList()
    },
    handleQueryStatusChange () {
      this.getPositionList()
    },
    filterTags (value, row) {
      return row.status === value
    },
    handleJumpToKline (row) {
      // 夜盘交易，时间算第二天的
      // this.$parent.jumpToKline(symbol)
      // 结束状态 k线页面不获取持仓信息
      let date
      let path
      let routeUrl
      if (row.status === 'winEnd' || row.status === 'loseEnd') {
        const tempDate = row.date_created.replace(/-/g, '/')
        date = new Date(tempDate)
        path = 'multi-period'
        const nextDay = date.getTime() + 3600 * 1000 * 24
        const endDate = CommonTool.parseTime(nextDay, '{y}-{m}-{d}')
        // routeUrl = this.$router.resolve({
        //     path: path,
        //     query: {
        //         period: row.period,
        //         symbol: row.symbol,
        //         isPosition: true, // 是否持过仓
        //         positionPeriod: row.period, // 开仓周期
        //         positionDirection: row.direction, // 持仓方向
        //         positionStatus: row.status, // 当前状态
        //         endDate: endDate
        //     }
        // });
        routeUrl = this.$router.resolve({
          path,
          query: {
            symbol: row.symbol,
            isPosition: true, // 是否持过仓
            positionPeriod: row.period, // 开仓周期
            positionDirection: row.direction, // 持仓方向
            positionStatus: row.status, // 当前状态
            endDate
          }
        })
      } else {
        date = new Date()
        path = 'multi-period'
        const nextDay = date.getTime() + 3600 * 1000 * 24
        const endDate = CommonTool.parseTime(nextDay, '{y}-{m}-{d}')
        routeUrl = this.$router.resolve({
          path,
          query: {
            symbol: row.symbol,
            isPosition: true, // 是否持过仓
            positionPeriod: row.period, // 开仓周期
            positionDirection: row.direction, // 持仓方向
            positionStatus: row.status, // 当前状态
            endDate
          }
        })
      }
      window.open(routeUrl.href, '_blank')
    },
    getPositionList () {
      // this.positionList = [];
      // this.listLoading = true;
      const requesting = this.$cache.get(
        `POSITION_LIST#${this.positionQueryForm.status}#${this.listQuery.current}#${this.listQuery.size}#${this.endDate}`
      )
      if (!requesting) {
        this.$cache.set(
          `POSITION_LIST#${this.positionQueryForm.status}#${this.listQuery.current}#${this.listQuery.size}#${this.endDate}`,
          true,
          60
        )
        futureApi
          .getPositionList(
            this.positionQueryForm.status,
            this.listQuery.current,
            this.listQuery.size,
            this.endDate
          )
          .then(res => {
            this.listLoading = false
            this.listQuery.total = res.total
            this.positionList = res.records
            this.processSum()
            // console.log("后端返回的持仓列表", res);
            this.$cache.del(
              `POSITION_LIST#${this.positionQueryForm.status}#${this.listQuery.current}#${this.listQuery.size}#${this.endDate}`
            )
          })
          .catch(() => {
            // this.listLoading = false;
            this.$cache.del(
              `POSITION_LIST#${this.positionQueryForm.status}#${this.listQuery.current}#${this.listQuery.size}#${this.endDate}`
            )
          })
      }
    },
    handleModifyStatus (row, status) {
      this.$message({
        message: '操作Success',
        type: 'success'
      })
      row.status = status
    },

    resetForm () {
      this.positionForm = {
        // importance: 1,
        enterTime: new Date(),
        symbol: '',
        period: '3m',
        status: 'holding',
        signal: '',
        direction: '',
        price: '',
        amount: '',
        stopLosePrice: '',
        // nestLevel: "2级套",
        enterReason: '',
        holdReason: '',
        dynamicPositionList: []
      }
    },
    addDynamicPosition () {
      this.positionForm.dynamicPositionList.push({
        time: new Date(),
        price: '',
        amount: '',
        reason: ''
      })
    },
    removeDynamicPosition (index) {
      this.positionForm.dynamicPositionList.splice(index, 1)
    },
    // 新增持仓
    handleCreatePos () {
      this.resetForm()
      this.dialogStatus = 'create'
      this.dialogFormVisible = true
      this.$nextTick(() => {
        this.$refs.positionFormRef.clearValidate()
      })
    },
    createData () {
      this.$refs.positionFormRef.validate(valid => {
        if (valid) {
          this.submitBtnLoading = true
          // 保存当时的保证金比率，方便计算 交割后的老的合约盈利率
          this.positionForm.margin_rate = this.futureSymbolMap[
            this.positionForm.symbol
          ].margin_rate
          futureApi
            .createPosition(this.positionForm)
            .then(() => {
              this.submitBtnLoading = false
              this.dialogFormVisible = false
              this.$notify({
                title: 'Success',
                message: '新增成功',
                type: 'success',
                duration: 2000
              })
              // 拉取后端接口获取最新持仓列表
              this.getPositionList()
            })
            .catch(() => {
              this.submitBtnLoading = false
              this.$notify({
                title: 'Error',
                message: '新增失败',
                type: 'error',
                duration: 2500
              })
            })
        }
      })
    },
    handleUpdate (row) {
      // this.positionForm = Object.assign({}, row); // copy obj
      this.positionForm = JSON.parse(JSON.stringify(row))
      this.dialogStatus = 'update'
      this.dialogFormVisible = true
      this.$nextTick(() => {
        this.$refs.positionFormRef.clearValidate()
      })
    },
    updateData () {
      this.$refs.positionFormRef.validate(valid => {
        if (valid) {
          this.submitBtnLoading = true
          // const tempData = Object.assign({}, this.positionForm)
          this.positionForm.margin_rate = this.futureSymbolMap[
            this.positionForm.symbol
          ].margin_rate
          futureApi
            .updatePosition(this.positionForm)
            .then(() => {
              this.submitBtnLoading = false
              this.dialogFormVisible = false
              this.$notify({
                title: 'Success',
                message: '更新成功',
                type: 'success',
                duration: 2000
              })
              // 拉取后端接口获取最新持仓列表
              this.getPositionList()
            })
            .catch(() => {
              this.submitBtnLoading = false
              this.$notify({
                title: 'Error',
                message: '更新持仓失败',
                type: 'error',
                duration: 2500
              })
            })
        }
      })
    },
    handleDelete (row, index) {
      this.$notify({
        title: 'Success',
        message: 'Delete Successfully',
        type: 'success',
        duration: 2000
      })
      this.positionList.splice(index, 1)
    },

    processSum () {
      // 将内盘和外盘 分开计算
      this.globalSumObj = {
        // 当前盈利
        currentProfitSum: 0,
        // 保证金
        marginSum: 0,
        // 已盈利
        winEndSum: 0,
        // 已止损
        loseEndSum: 0,
        // 预计止损
        predictStopSum: 0
      }
      this.sumObj = {
        // 当前盈利
        currentProfitSum: 0,
        // 当前盈利占总账户比例
        currentProfitSumRate: 0,
        // 保证金
        marginSum: 0,
        // 已盈利
        winEndSum: 0,
        // 已盈利占总账户比例
        winEndSumRate: 0,

        // 已止损
        loseEndSum: 0,
        // 预计止损
        predictStopSum: 0,
        // 保证金占用总账户比例
        marginSumRate: 0
      }
      for (let i = 0; i < this.positionList.length; i++) {
        const item = this.positionList[i]
        // 外盘期货
        if (this.globalFutureSymbol.indexOf(item.symbol) !== -1) {
          if (item.status === 'holding') {
            this.globalSumObj.currentProfitSum += parseInt(item.current_profit)
            this.globalSumObj.predictStopSum += parseInt(
              item.predict_stop_money
            )
          }
          this.globalSumObj.winEndSum += Math.round(item.win_end_money, 0)
          this.globalSumObj.loseEndSum += Math.round(item.lose_end_money, 0)
          this.globalSumObj.marginSum += Math.round(item.total_margin, 0)
        } else {
          // 内盘期货
          if (item.status === 'holding') {
            this.sumObj.currentProfitSum += parseInt(item.current_profit)
            this.sumObj.predictStopSum += parseInt(item.predict_stop_money)
          }
          if (this.positionQueryForm.status === 'winEnd') {
            this.sumObj.winEndSum += parseInt(item.win_end_money)
          }
          // 判断是否 动止过，如果动止 盈利 = 当前浮盈+ 已动止的盈利
          if (
            Object.hasOwnProperty(item, 'dynamicPositionList') &&
            item.dynamicPositionList.length !== 0
          ) {
            let dynamicWinSum = 0
            for (let j = 0; j < item.dynamicPositionList.length; j++) {
              dynamicWinSum += item.dynamicPositionList[j].stop_win_money
            }
            this.sumObj.winEndSum += parseInt(dynamicWinSum)
            // console.log(item.symbol, dynamicWinSum)
          }
          // 由于程序性能问题 实际扫描到止损的时候价格已经越过止损价了 因此这里使用预计止损额更准确
          this.sumObj.loseEndSum += Math.round(item.predict_stop_money, 0)
          this.sumObj.marginSum += Math.round(item.total_margin, 0)
          this.sumObj.marginSumRate =
            (
              (this.sumObj.marginSum / (futureAccount * 10000)) *
              100
            ).toFixed(1) + '%'
          this.sumObj.winEndSumRate =
            (
              (this.sumObj.winEndSum / (futureAccount * 10000)) *
              100
            ).toFixed(1) + '%'
          this.sumObj.currentProfitSumRate =
            (
              (this.sumObj.currentProfitSum / (futureAccount * 10000)) *
              100
            ).toFixed(1) + '%'
        }
      }
    },
    getSummaries (param) {
      const { columns, data } = param
      const sums = []
      let stopSum = 0
      let currentProfitSum = 0
      // 占用保证金
      let totalMargin = 0
      // 已止损
      let loseEndSum = 0
      // 已盈利
      let winEndSum = 0
      if (data.length === 0) {
        return sums
      }
      columns.forEach((column, index) => {
        const label = column.label
        if (label === '品种') {
          sums[index] = '合计'
          return
        }
        // 累加 预计止损
        if (label === '止损额') {
          data.forEach(item => {
            stopSum += item.predict_stop_money
          })
          sums[index] = stopSum
        } else if (label === '实际亏损额') {
          // 累加已止损
          data.forEach(item => {
            if (item.status === 'loseEnd') {
              loseEndSum += item.lose_end_money
            }
          })
          sums[index] = parseInt(loseEndSum)
        } else if (label === '已盈利额') {
          // 累加已盈利
          data.forEach(item => {
            if (item.status === 'winEnd') {
              winEndSum += item.win_end_money
            }
          })
          sums[index] = parseInt(winEndSum)
        } else if (label === '已盈利比率') {
          sums[index] =
            (
              (this.sumObj.winEndSum / (futureAccount * 10000)) *
              100
            ).toFixed(1) + '%'
        } else if (label === '浮盈额') {
          // 累加当前盈利
          data.forEach(item => {
            // 只累加还在持仓中的
            if (item.status === 'holding') {
              currentProfitSum += item.current_profit
            }
          })
          sums[index] = parseInt(currentProfitSum)
        } else if (label === '保证金') {
          // 累加当前保证金
          data.forEach(item => {
            // 只累加还在持仓中的
            // if (item.status === 'holding') {
            // 兼容老数据
            if (item.total_margin) {
              totalMargin += item.total_margin
            }
            // }
          })
          sums[index] = totalMargin
        } else if (label === '浮盈率') {
          sums[index] =
            (
              (this.sumObj.currentProfitSum / (futureAccount * 10000)) *
              100
            ).toFixed(1) + '%'
        } else if (label === '止损率') {
          sums[index] =
            (
              (this.sumObj.loseEndSum / (futureAccount * 10000)) *
              100
            ).toFixed(1) + '%'
        } else {
          sums[index] = ''
        }
      })
      return sums
    }
    // formatJson(filterVal) {
    //     return this.positionList.map(v => filterVal.map(j => {
    //         if (j === 'enterTime') {
    //             return parseTime(v[j])
    //         } else {
    //             return v[j]
    //         }
    //     }))
    // },
    // getSortClass: function (key) {
    //     const sort = this.positionListQuery.sort
    //     return sort === `+${key}` ? 'ascending' : 'descending'
    // }
  }
}
</script>
<style lang="stylus">
.position-list-main {
    .up-red {
        color: #D04949
    }

    .down-green {
        color: #279D61
    }

    .zero-gray {
        color: #606266
    }

    .primary-color {
        color: white !important
    }

    // element-ui table

    //下拉选项

    .el-select-dropdown {
        background: #12161c !important
    }

    .el-select-dropdown__item.hover, .el-select-dropdown__item:hover {
        background-color: #0B0E11 !important;
    }

    .el-table--enable-row-hover .el-table__body tr:hover > td {
        background-color: #0B0E11;
    }

    //表行间隔色

    .el-table td, .building-top .el-table th.is-leaf {
        border-bottom: 1px solid #0B0E11;
    }

    //表头间隔色

    .el-table td, .el-table th.is-leaf {
        border-bottom: 1px solid #0B0E11;
    }

    //表尾间隔色

    .el-table--border::after, .el-table--group::after, .el-table::before {
        border-bottom: 1px solid #0B0E11;
        background: #0B0E11
    }

    //折叠行背景

    td.el-table__expanded-cell {
        background: #0B0E11
    }

    .el-table__expanded-cell:hover {
        background: #0B0E11 !important
    }

    .el-header-cell {
        background: #12161c;
        color: #d4d0c6
    }

    .el-cell {
        background: #12161c;
        color: #d4d0c6
    }

    .el-table__empty-block {
        background: #0B0E11;
    }

    .el-table__empty-text {
        color: white
    }

    .el-table__footer-wrapper td {
        background: #12161c
        color: #D04949
        border-top: #0B0E11
    }

    .form-input {
        width: 200px !important;
    }

    .form-input-short {
        width: 100px !important;
    }

    .long-textarea {
        width: 350px;
    }

    .form-textarea-middle {
        width: 600px;
    }

    .form-textarea-long {
        width: 1000px;
    }

    .query-position-form {
        margin-bottom: 10px;
    }

    .el-table .warning-row {
        background: oldlace;
    }

    .el-table .success-row {
        background: #f0f9eb;
    }

    .sum-text {
        font-size: 20px;
    }
}
</style>
