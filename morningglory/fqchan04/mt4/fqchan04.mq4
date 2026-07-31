//+------------------------------------------------------------------+
//|                                                       fqchan04.mq4 |
//|                             Copyright 2000-2026, MetaQuotes Ltd. |
//|                                                     www.mql5.com |
//+------------------------------------------------------------------+
#property copyright "公众号：kldctymp"
#property link      "https://mp.weixin.qq.com/s/xKBIlmBp9iyYg7wpLc5bPw"
#property version   "1.00"
#property indicator_chart_window
#property indicator_buffers 4

#property indicator_color1  clrYellow
#property indicator_width1  2
#property indicator_color2  clrBlue
#property indicator_width2  2
#property indicator_color3  clrMagenta
#property indicator_width3  2
#property indicator_color4  clrNONE

//--- input parameters
input int InpBiMode = 5;  // 笔模式：4=4K笔, 5=5K笔, 6=大笔(严格)
input color InpBiZSColor = clrYellow;  // 笔中枢矩形颜色
input color InpTrendZSColor = clrBlue;  // 线段中枢矩形颜色
input int InpZSStyle = STYLE_SOLID;  // 中枢矩形样式
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

//--- 全局变量
string g_bi_line_prefix = "BiLine_";
string g_duan_line_prefix = "DuanLine_";
string g_trend_line_prefix = "TrendLine_";
int g_last_bars = 0;

//+------------------------------------------------------------------+
//| Custom indicator initialization function                         |
//+------------------------------------------------------------------+
int OnInit()
{
   SetIndexBuffer(0, BiBuffer);
   SetIndexBuffer(1, DuanBuffer);
   SetIndexBuffer(2, TrendBuffer);
   SetIndexBuffer(3, ZSBuffer);

   SetIndexStyle(0, DRAW_NONE);
   SetIndexStyle(1, DRAW_NONE);
   SetIndexStyle(2, DRAW_NONE);
   SetIndexStyle(3, DRAW_NONE);

   SetIndexLabel(0, "Bi");
   SetIndexLabel(1, "Duan");
   SetIndexLabel(2, "Trend");
   SetIndexLabel(3, "ZS");

   string short_name = StringFormat("Bi(%d)", InpBiMode);
   IndicatorShortName(short_name);

   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Custom indicator deinitialization function                       |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   DeleteAllObjects("BiZS_");
   DeleteAllObjects("TrendZS_");
   DeleteAllObjects(g_bi_line_prefix);
   DeleteAllObjects(g_duan_line_prefix);
   DeleteAllObjects(g_trend_line_prefix);
}

//+------------------------------------------------------------------+
//| 删除所有指定前缀的对象                                            |
//+------------------------------------------------------------------+
void DeleteAllObjects(string prefix)
{
   for(int i = ObjectsTotal() - 1; i >= 0; i--)
   {
      string name = ObjectName(i);
      if(StringFind(name, prefix) == 0)
         ObjectDelete(name);
   }
}

//+------------------------------------------------------------------+
//| 画中枢矩形对象                                                   |
//+------------------------------------------------------------------+
void DrawZSRectangle(int start, int end, double zg, double zd, int index, string prefix, color clr)
{
   string name = prefix + IntegerToString(index);

   ObjectDelete(name);

   if(ObjectCreate(name, OBJ_RECTANGLE, 0, Time[start], zg, Time[end], zd))
   {
      ObjectSet(name, OBJPROP_COLOR, clr);
      ObjectSet(name, OBJPROP_STYLE, InpZSStyle);
      ObjectSet(name, OBJPROP_WIDTH, InpZSWidth);
      ObjectSet(name, OBJPROP_BACK, true);
   }
}

//+------------------------------------------------------------------+
//| 画连线（笔、段、走势）                                            |
//+------------------------------------------------------------------+
void DrawLines(double &buffer[], string prefix, color clr, int width)
{
   DeleteAllObjects(prefix);

   int line_index = 0;
   int last_point = -1;
   double last_price = 0;

   for(int i = Bars - 1; i >= 0; i--)
   {
      if(buffer[i] != 0.0)
      {
         if(last_point >= 0)
         {
            string name = prefix + IntegerToString(line_index++);
            if(ObjectCreate(name, OBJ_TREND, 0, Time[last_point], last_price, Time[i], buffer[i]))
            {
               ObjectSet(name, OBJPROP_COLOR, clr);
               ObjectSet(name, OBJPROP_WIDTH, width);
               ObjectSet(name, OBJPROP_STYLE, STYLE_SOLID);
               ObjectSet(name, OBJPROP_RAY, false);
               ObjectSet(name, OBJPROP_BACK, false);
            }
         }
         last_point = i;
         last_price = buffer[i];
      }
   }
}

//+------------------------------------------------------------------+
//| 缠论笔计算                                                     |
//+------------------------------------------------------------------+
int start()
{
   if(Bars < 1)
      return(0);

   if(Bars == g_last_bars)
      return(0);

   ArrayInitialize(BiBuffer, 0.0);
   ArrayInitialize(DuanBuffer, 0.0);
   ArrayInitialize(TrendBuffer, 0.0);
   ArrayInitialize(ZSBuffer, 0.0);

   double high_arr[], low_arr[];
   ArrayResize(high_arr, Bars);
   ArrayResize(low_arr, Bars);

   for(int i = 0; i < Bars; i++)
   {
      high_arr[Bars - 1 - i] = High[i];
      low_arr[Bars - 1 - i] = Low[i];
   }

   double bi_temp[], duan_temp[], trend_temp[];
   ArrayResize(bi_temp, Bars);
   ArrayResize(duan_temp, Bars);
   ArrayResize(trend_temp, Bars);
   ArrayInitialize(bi_temp, 0.0);
   ArrayInitialize(duan_temp, 0.0);
   ArrayInitialize(trend_temp, 0.0);

   FQ_BI(Bars, bi_temp, high_arr, low_arr, InpBiMode);
   FQ_DUAN(Bars, duan_temp, high_arr, low_arr, bi_temp);
   FQ_TREND(Bars, trend_temp, duan_temp, high_arr, low_arr);

   double BiZGBuffer[], BiZDBuffer[], BiZSEBuffer[];
   ArrayResize(BiZGBuffer, Bars);
   ArrayResize(BiZDBuffer, Bars);
   ArrayResize(BiZSEBuffer, Bars);
   ArrayInitialize(BiZGBuffer, 0.0);
   ArrayInitialize(BiZDBuffer, 0.0);
   ArrayInitialize(BiZSEBuffer, 0.0);

   FQ_ZSZG(Bars, BiZGBuffer, duan_temp, bi_temp, high_arr, low_arr, InpBiMode);
   FQ_ZSZD(Bars, BiZDBuffer, duan_temp, bi_temp, high_arr, low_arr, InpBiMode);
   FQ_ZSSE(Bars, BiZSEBuffer, duan_temp, bi_temp, high_arr, low_arr, InpBiMode);

   double TrendZGBuffer[], TrendZDBuffer[], TrendZSEBuffer[];
   ArrayResize(TrendZGBuffer, Bars);
   ArrayResize(TrendZDBuffer, Bars);
   ArrayResize(TrendZSEBuffer, Bars);
   ArrayInitialize(TrendZGBuffer, 0.0);
   ArrayInitialize(TrendZDBuffer, 0.0);
   ArrayInitialize(TrendZSEBuffer, 0.0);

   FQ_ZSZG(Bars, TrendZGBuffer, trend_temp, duan_temp, high_arr, low_arr, InpBiMode);
   FQ_ZSZD(Bars, TrendZDBuffer, trend_temp, duan_temp, high_arr, low_arr, InpBiMode);
   FQ_ZSSE(Bars, TrendZSEBuffer, trend_temp, duan_temp, high_arr, low_arr, InpBiMode);

   for(int j = 0; j < Bars; j++)
   {
      int idx = Bars - 1 - j;

      if(bi_temp[j] == 1.0)
      {
         BiBuffer[idx] = High[idx];
      }
      else if(bi_temp[j] == -1.0)
      {
         BiBuffer[idx] = Low[idx];
      }
      else
      {
         BiBuffer[idx] = 0.0;
      }

      if(duan_temp[j] == 1.0)
      {
         DuanBuffer[idx] = High[idx];
      }
      else if(duan_temp[j] == -1.0)
      {
         DuanBuffer[idx] = Low[idx];
      }
      else
      {
         DuanBuffer[idx] = 0.0;
      }

      if(trend_temp[j] == 1.0)
      {
         TrendBuffer[idx] = High[idx];
      }
      else if(trend_temp[j] == -1.0)
      {
         TrendBuffer[idx] = Low[idx];
      }
      else
      {
         TrendBuffer[idx] = 0.0;
      }
   }

   DrawLines(BiBuffer, g_bi_line_prefix, clrYellow, 2);
   DrawLines(DuanBuffer, g_duan_line_prefix, clrBlue, 2);
   DrawLines(TrendBuffer, g_trend_line_prefix, clrMagenta, 2);

   DeleteAllObjects("BiZS_");
   int bi_zs_index = 0;
   for(int k = 0; k < Bars; k++)
   {
      int idx2 = Bars - 1 - k;
      if(BiZSEBuffer[k] == 1.0)
      {
         int start_bi = idx2;
         for(int m = k + 1; m < Bars; m++)
         {
            if(BiZSEBuffer[m] == 2.0)
            {
               int end_bi = Bars - 1 - m;
               double zg_bi = BiZGBuffer[k];
               double zd_bi = BiZDBuffer[k];
               DrawZSRectangle(start_bi, end_bi, zg_bi, zd_bi, bi_zs_index++, "BiZS_", InpBiZSColor);
               k = m;
               break;
            }
         }
      }
   }

   DeleteAllObjects("TrendZS_");
   int trend_zs_index = 0;
   for(int n = 0; n < Bars; n++)
   {
      int idx3 = Bars - 1 - n;
      if(TrendZSEBuffer[n] == 1.0)
      {
         int start_trend = idx3;
         for(int p = n + 1; p < Bars; p++)
         {
            if(TrendZSEBuffer[p] == 2.0)
            {
               int end_trend = Bars - 1 - p;
               double zg_trend = TrendZGBuffer[n];
               double zd_trend = TrendZDBuffer[n];
               DrawZSRectangle(start_trend, end_trend, zg_trend, zd_trend, trend_zs_index++, "TrendZS_", InpTrendZSColor);
               n = p;
               break;
            }
         }
      }
   }

   g_last_bars = Bars;

   return(0);
}
//+------------------------------------------------------------------+
