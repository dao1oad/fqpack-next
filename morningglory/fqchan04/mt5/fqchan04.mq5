//+------------------------------------------------------------------+
//|                                                       fqchan04.mq5 |
//|                             Copyright 2000-2026, MetaQuotes Ltd. |
//|                                                     www.mql5.com |
//+------------------------------------------------------------------+
#property copyright "公众号：mywildquant"
#property link      "https://mp.weixin.qq.com/s/xKBIlmBp9iyYg7wpLc5bPw"
#property version   "1.00"
#property indicator_chart_window
#property indicator_buffers 4
#property indicator_plots   4
//--- plot 1：笔
#property indicator_label1  "Bi"
#property indicator_type1   DRAW_SECTION
#property indicator_color1  clrYellow
#property indicator_style1  STYLE_SOLID
#property indicator_width1  2
//--- plot 2：段
#property indicator_label2  "Duan"
#property indicator_type2   DRAW_SECTION
#property indicator_color2  clrBlue
#property indicator_style2  STYLE_SOLID
#property indicator_width2  2
//--- plot 3：走势类型连线
#property indicator_label3  "Trend"
#property indicator_type3   DRAW_SECTION
#property indicator_color3  clrMagenta
#property indicator_style3  STYLE_SOLID
#property indicator_width3  2
//--- plot 4：中枢（辅助，不显示）
#property indicator_label4  "ZS"
#property indicator_type4   DRAW_NONE
#property indicator_color4  clrNONE
//--- input parameters
input int InpBiMode = 5;  // 笔模式：4=4K笔, 5=5K笔, 6=大笔(严格)
input color InpBiZSColor = clrYellow;  // 笔中枢矩形颜色
input color InpTrendZSColor = clrBlue;  // 线段中枢矩形颜色
input ENUM_LINE_STYLE InpZSStyle = STYLE_SOLID;  // 中枢矩形样式
input int InpZSWidth = 1;  // 中枢矩形宽度
input bool InpZSFill = false;  // 是否填充中枢矩形
//--- indicator buffers
double    BiBuffer[];   // 缠论笔信号：1=笔顶, -1=笔底
double    DuanBuffer[];  // 缠论段信号
double    TrendBuffer[]; // 缠论走势类型连线
double    ZSBuffer[];   // 缠论中枢数据（用于检测中枢边界）
//--- import DLL
#import "fqchan04.dll"
   void FQ_BI(int count, double &out[], const double &high[], const double &low[], int bi_mode);
   void FQ_DUAN(int count, double &out[], const double &high[], const double &low[], const double &bi[]);
   void FQ_TREND(int count, double &out[], const double &duan[], const double &high[], const double &low[]);
   void FQ_ZSZG(int count, double &out[], const double &duan[], const double &bi[], const double &high[], const double &low[], int bi_mode);
   void FQ_ZSZD(int count, double &out[], const double &duan[], const double &bi[], const double &high[], const double &low[], int bi_mode);
   void FQ_ZSSE(int count, double &out[], const double &duan[], const double &bi[], const double &high[], const double &low[], int bi_mode);
#import

//+------------------------------------------------------------------+
//| Custom indicator initialization function                         |
//+------------------------------------------------------------------+
void OnInit()
  {
//--- indicator buffers mapping
   SetIndexBuffer(0,BiBuffer,INDICATOR_DATA);
   SetIndexBuffer(1,DuanBuffer,INDICATOR_DATA);
   SetIndexBuffer(2,TrendBuffer,INDICATOR_DATA);
   SetIndexBuffer(3,ZSBuffer,INDICATOR_CALCULATIONS);  // 用于计算，不显示
//--- set short name and digits
   string short_name=StringFormat("Bi(%d)",InpBiMode);
   IndicatorSetString(INDICATOR_SHORTNAME,short_name);
   PlotIndexSetString(0,PLOT_LABEL,short_name);
   PlotIndexSetString(1,PLOT_LABEL,"Duan");
   PlotIndexSetString(2,PLOT_LABEL,"Trend");
   IndicatorSetInteger(INDICATOR_DIGITS,_Digits);
//--- set an empty value
   PlotIndexSetDouble(0,PLOT_EMPTY_VALUE,0.0);
   PlotIndexSetDouble(1,PLOT_EMPTY_VALUE,0.0);
   PlotIndexSetDouble(2,PLOT_EMPTY_VALUE,0.0);
  }

//+------------------------------------------------------------------+
//| Custom indicator deinitialization function                       |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
//--- 删除所有中枢矩形对象
   ObjectsDeleteAll(0, "BiZS_");     // 删除笔中枢对象
   ObjectsDeleteAll(0, "TrendZS_"); // 删除线段中枢对象
   ChartRedraw(0);
  }

//+------------------------------------------------------------------+
//| 画中枢矩形对象                                                   |
//+------------------------------------------------------------------+
void DrawZSRectangle(const datetime &time[], const double &high[], const double &low[],
                     int start, int end, double zg, double zd, int index, string prefix, color clr)
  {
   string name = prefix + IntegerToString(index);

   //--- 删除旧对象（如果存在）
   ObjectDelete(0, name);

   //--- 创建矩形对象
   if(ObjectCreate(0, name, OBJ_RECTANGLE, 0, time[start], zg, time[end], zd))
     {
      ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
      ObjectSetInteger(0, name, OBJPROP_STYLE, InpZSStyle);
      ObjectSetInteger(0, name, OBJPROP_WIDTH, InpZSWidth);
      ObjectSetInteger(0, name, OBJPROP_FILL, InpZSFill);
      ObjectSetInteger(0, name, OBJPROP_BACK, true);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
     }
  }

//+------------------------------------------------------------------+
//| 缠论笔计算                                                     |
//+------------------------------------------------------------------+
int OnCalculate(const int rates_total,
                const int prev_calculated,
                const datetime &time[],
                const double &open[],
                const double &high[],
                const double &low[],
                const double &close[],
                const long &tick_volume[],
                const long &volume[],
                const int &spread[])
  {
   if(rates_total<1)
      return(0);
//---
   ArrayInitialize(BiBuffer,0.0);
   ArrayInitialize(DuanBuffer,0.0);
   ArrayInitialize(TrendBuffer,0.0);
   ArrayInitialize(ZSBuffer,0.0);

   // 先计算笔
   FQ_BI(rates_total, BiBuffer, high, low, InpBiMode);

   // 再计算段（需要笔的结果）
   FQ_DUAN(rates_total, DuanBuffer, high, low, BiBuffer);

   // 计算走势类型（需要段的结果）
   FQ_TREND(rates_total, TrendBuffer, DuanBuffer, high, low);

   // 计算笔中枢（段+笔）
   double BiZGBuffer[], BiZDBuffer[], BiZSEBuffer[];
   ArrayResize(BiZGBuffer, rates_total);
   ArrayResize(BiZDBuffer, rates_total);
   ArrayResize(BiZSEBuffer, rates_total);
   ArrayInitialize(BiZGBuffer, 0.0);
   ArrayInitialize(BiZDBuffer, 0.0);
   ArrayInitialize(BiZSEBuffer, 0.0);

   FQ_ZSZG(rates_total, BiZGBuffer, DuanBuffer, BiBuffer, high, low, InpBiMode);
   FQ_ZSZD(rates_total, BiZDBuffer, DuanBuffer, BiBuffer, high, low, InpBiMode);
   FQ_ZSSE(rates_total, BiZSEBuffer, DuanBuffer, BiBuffer, high, low, InpBiMode);

   // 计算线段中枢（走势+段）
   double TrendZGBuffer[], TrendZDBuffer[], TrendZSEBuffer[];
   ArrayResize(TrendZGBuffer, rates_total);
   ArrayResize(TrendZDBuffer, rates_total);
   ArrayResize(TrendZSEBuffer, rates_total);
   ArrayInitialize(TrendZGBuffer, 0.0);
   ArrayInitialize(TrendZDBuffer, 0.0);
   ArrayInitialize(TrendZSEBuffer, 0.0);

   FQ_ZSZG(rates_total, TrendZGBuffer, TrendBuffer, DuanBuffer, high, low, InpBiMode);
   FQ_ZSZD(rates_total, TrendZDBuffer, TrendBuffer, DuanBuffer, high, low, InpBiMode);
   FQ_ZSSE(rates_total, TrendZSEBuffer, TrendBuffer, DuanBuffer, high, low, InpBiMode);

   // 将笔信号值转换为实际价格
   for(int i = 0; i < rates_total; i++) {
      if(BiBuffer[i] == 1.0) {
         BiBuffer[i] = high[i];  // 笔顶用最高价
      } else if(BiBuffer[i] == -1.0) {
         BiBuffer[i] = low[i];   // 笔底用最低价
      } else {
         BiBuffer[i] = 0.0;       // 其他值设为空值
      }
   }

   // 将段信号值转换为实际价格（只保留端点）
   for(int i = 0; i < rates_total; i++) {
      float val = DuanBuffer[i];
      if(val == 1.0) {          // 向上段终点
         DuanBuffer[i] = high[i];
      } else if(val == -1.0) {   // 向下段终点
         DuanBuffer[i] = low[i];
      } else {
         DuanBuffer[i] = 0.0;    // 其他值（中间点、普通点、段标识符等）设为空值
      }
   }

   // 将走势信号值转换为实际价格
   for(int i = 0; i < rates_total; i++) {
      if(TrendBuffer[i] == 1.0) {
         TrendBuffer[i] = high[i];  // 走势高点用最高价
      } else if(TrendBuffer[i] == -1.0) {
         TrendBuffer[i] = low[i];   // 走势低点用最低价
      } else {
         TrendBuffer[i] = 0.0;      // 其他值设为空值
      }
   }

   //--- 画笔中枢矩形对象
   int bi_zs_index = 0;
   for(int i = 0; i < rates_total; i++) {
      if(BiZSEBuffer[i] == 1.0) {  // 笔中枢起点
         int start = i;
         // 找到对应的终点
         for(int j = i + 1; j < rates_total; j++) {
            if(BiZSEBuffer[j] == 2.0) {  // 笔中枢终点
               int end = j;
               double zg = BiZGBuffer[start];  // 起点的ZG价格
               double zd = BiZDBuffer[start];  // 起点的ZD价格
               DrawZSRectangle(time, high, low, start, end, zg, zd, bi_zs_index++, "BiZS_", InpBiZSColor);
               i = j;  // 跳到终点位置
               break;
            }
         }
      }
   }

   //--- 画线段中枢矩形对象
   int trend_zs_index = 0;
   for(int i = 0; i < rates_total; i++) {
      if(TrendZSEBuffer[i] == 1.0) {  // 线段中枢起点
         int start = i;
         // 找到对应的终点
         for(int j = i + 1; j < rates_total; j++) {
            if(TrendZSEBuffer[j] == 2.0) {  // 线段中枢终点
               int end = j;
               double zg = TrendZGBuffer[start];  // 起点的ZG价格
               double zd = TrendZDBuffer[start];  // 起点的ZD价格
               DrawZSRectangle(time, high, low, start, end, zg, zd, trend_zs_index++, "TrendZS_", InpTrendZSColor);
               i = j;  // 跳到终点位置
               break;
            }
         }
      }
   }

   return(rates_total);
  }
//+------------------------------------------------------------------+
