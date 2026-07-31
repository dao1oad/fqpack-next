//+------------------------------------------------------------------+
//|                                                   fqcopilot.mq5  |
//|                                    FQCopilot Signal Indicator  |
//|                                                                  |
//+------------------------------------------------------------------+
#property copyright "FQCopilot"
#property link      ""
#property version   "1.00"
#property indicator_chart_window
#property indicator_buffers 13
#property indicator_plots   13

//--- plot S0000
#property indicator_label1  "S0000"
#property indicator_type1   DRAW_NONE
#property indicator_color1  clrNONE
#property indicator_style1  STYLE_SOLID
#property indicator_width1  1

//--- plot S0001
#property indicator_label2  "S0001"
#property indicator_type2   DRAW_NONE
#property indicator_color2  clrNONE
#property indicator_style2  STYLE_SOLID
#property indicator_width2  1

//--- plot S0002
#property indicator_label3  "S0002"
#property indicator_type3   DRAW_NONE
#property indicator_color3  clrNONE
#property indicator_style3  STYLE_SOLID
#property indicator_width3  1

//--- plot S0003
#property indicator_label4  "S0003"
#property indicator_type4   DRAW_NONE
#property indicator_color4  clrNONE
#property indicator_style4  STYLE_SOLID
#property indicator_width4  1

//--- plot S0004
#property indicator_label5  "S0004"
#property indicator_type5   DRAW_NONE
#property indicator_color5  clrNONE
#property indicator_style5  STYLE_SOLID
#property indicator_width5  1

//--- plot S0005
#property indicator_label6  "S0005"
#property indicator_type6   DRAW_NONE
#property indicator_color6  clrNONE
#property indicator_style6  STYLE_SOLID
#property indicator_width6  1

//--- plot S0006
#property indicator_label7  "S0006"
#property indicator_type7   DRAW_NONE
#property indicator_color7  clrNONE
#property indicator_style7  STYLE_SOLID
#property indicator_width7  1

//--- plot S0007
#property indicator_label8  "S0007"
#property indicator_type8   DRAW_NONE
#property indicator_color8  clrNONE
#property indicator_style8  STYLE_SOLID
#property indicator_width8  1

//--- plot S0008
#property indicator_label9  "S0008"
#property indicator_type9   DRAW_NONE
#property indicator_color9  clrNONE
#property indicator_style9  STYLE_SOLID
#property indicator_width9  1

//--- plot S0009
#property indicator_label10 "S0009"
#property indicator_type10  DRAW_NONE
#property indicator_color10  clrNONE
#property indicator_style10 STYLE_SOLID
#property indicator_width10  1

//--- plot S0010
#property indicator_label11 "S0010"
#property indicator_type11  DRAW_NONE
#property indicator_color11  clrNONE
#property indicator_style11 STYLE_SOLID
#property indicator_width11  1

//--- plot S0011
#property indicator_label12 "S0011"
#property indicator_type12  DRAW_NONE
#property indicator_color12  clrNONE
#property indicator_style12 STYLE_SOLID
#property indicator_width12  1

//--- plot S0012
#property indicator_label13 "S0012"
#property indicator_type13  DRAW_NONE
#property indicator_color13  clrNONE
#property indicator_style13 STYLE_SOLID
#property indicator_width13  1

//--- input parameters
input int      Wave_Opt    = 1550;     // 波浪选项
input int      Stretch_Opt = 1;        // 线段选项
input int      Trend_Opt   = 1;        // 趋势选项

input bool     Show_S0000  = false;    // 显示 S0000 信号
input bool     Show_S0001  = true;     // 显示 S0001 信号
input bool     Show_S0002  = false;    // 显示 S0002 信号
input bool     Show_S0003  = false;    // 显示 S0003 信号
input bool     Show_S0004  = false;    // 显示 S0004 信号
input bool     Show_S0005  = false;    // 显示 S0005 信号
input bool     Show_S0006  = false;    // 显示 S0006 信号
input bool     Show_S0007  = false;    // 显示 S0007 信号
input bool     Show_S0008  = false;    // 显示 S0008 信号
input bool     Show_S0009  = false;    // 显示 S0009 信号
input bool     Show_S0010  = false;    // 显示 S0010 信号
input bool     Show_S0011  = false;    // 显示 S0011 信号
input bool     Show_S0012  = false;    // 显示 S0012 信号

input color    Buy_Color   = clrRed;   // 买入信号颜色
input color    Sell_Color  = clrLime;  // 卖出信号颜色
input int      Arrow_Size  = 3;        // 箭头大小

//--- indicator buffers
double BufferS0000[];
double BufferS0001[];
double BufferS0002[];
double BufferS0003[];
double BufferS0004[];
double BufferS0005[];
double BufferS0006[];
double BufferS0007[];
double BufferS0008[];
double BufferS0009[];
double BufferS0010[];
double BufferS0011[];
double BufferS0012[];

//--- DLL import
#import "fqcopilot.dll"
   void FQ_CLXS(
       int count,
       double &out[],
       const double &high[],
       const double &low[],
       const double &open[],
       const double &close[],
       const double &vol[],
       int wave_opt,
       int stretch_opt,
       int trend_opt,
       int model_opt
   );
#import

//+------------------------------------------------------------------+
//| Custom indicator initialization function                          |
//+------------------------------------------------------------------+
int OnInit()
{
   //--- set buffers
   SetIndexBuffer(0, BufferS0000, INDICATOR_DATA);
   SetIndexBuffer(1, BufferS0001, INDICATOR_DATA);
   SetIndexBuffer(2, BufferS0002, INDICATOR_DATA);
   SetIndexBuffer(3, BufferS0003, INDICATOR_DATA);
   SetIndexBuffer(4, BufferS0004, INDICATOR_DATA);
   SetIndexBuffer(5, BufferS0005, INDICATOR_DATA);
   SetIndexBuffer(6, BufferS0006, INDICATOR_DATA);
   SetIndexBuffer(7, BufferS0007, INDICATOR_DATA);
   SetIndexBuffer(8, BufferS0008, INDICATOR_DATA);
   SetIndexBuffer(9, BufferS0009, INDICATOR_DATA);
   SetIndexBuffer(10, BufferS0010, INDICATOR_DATA);
   SetIndexBuffer(11, BufferS0011, INDICATOR_DATA);
   SetIndexBuffer(12, BufferS0012, INDICATOR_DATA);

   //--- set empty values
   PlotIndexSetDouble(0, PLOT_EMPTY_VALUE, 0);
   PlotIndexSetDouble(1, PLOT_EMPTY_VALUE, 0);
   PlotIndexSetDouble(2, PLOT_EMPTY_VALUE, 0);
   PlotIndexSetDouble(3, PLOT_EMPTY_VALUE, 0);
   PlotIndexSetDouble(4, PLOT_EMPTY_VALUE, 0);
   PlotIndexSetDouble(5, PLOT_EMPTY_VALUE, 0);
   PlotIndexSetDouble(6, PLOT_EMPTY_VALUE, 0);
   PlotIndexSetDouble(7, PLOT_EMPTY_VALUE, 0);
   PlotIndexSetDouble(8, PLOT_EMPTY_VALUE, 0);
   PlotIndexSetDouble(9, PLOT_EMPTY_VALUE, 0);
   PlotIndexSetDouble(10, PLOT_EMPTY_VALUE, 0);
   PlotIndexSetDouble(11, PLOT_EMPTY_VALUE, 0);
   PlotIndexSetDouble(12, PLOT_EMPTY_VALUE, 0);

   //---
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Custom indicator deinitialization function                        |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   //--- 清理箭头对象
   ObjectsDeleteAll(0, "FQCopilot_");
}

//+------------------------------------------------------------------+
//| Custom indicator iteration function                               |
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
   if(rates_total < 10)
      return(0);

   //--- 计算起始位置
   int start;
   if(prev_calculated == 0)
   {
      start = 0;
      //--- 初始化缓冲区
      ArrayInitialize(BufferS0000, 0);
      ArrayInitialize(BufferS0001, 0);
      ArrayInitialize(BufferS0002, 0);
      ArrayInitialize(BufferS0003, 0);
      ArrayInitialize(BufferS0004, 0);
      ArrayInitialize(BufferS0005, 0);
      ArrayInitialize(BufferS0006, 0);
      ArrayInitialize(BufferS0007, 0);
      ArrayInitialize(BufferS0008, 0);
      ArrayInitialize(BufferS0009, 0);
      ArrayInitialize(BufferS0010, 0);
      ArrayInitialize(BufferS0011, 0);
      ArrayInitialize(BufferS0012, 0);
   }
   else
   {
      start = prev_calculated - 1;
   }

   //--- 准备数据数组
   double HighArray[];
   double LowArray[];
   double OpenArray[];
   double CloseArray[];
   double VolArray[];
   double OutArray[];

   ArraySetAsSeries(HighArray, false);
   ArraySetAsSeries(LowArray, false);
   ArraySetAsSeries(OpenArray, false);
   ArraySetAsSeries(CloseArray, false);
   ArraySetAsSeries(VolArray, false);
   ArraySetAsSeries(OutArray, false);

   ArrayCopy(HighArray, high);
   ArrayCopy(LowArray, low);
   ArrayCopy(OpenArray, open);
   ArrayCopy(CloseArray, close);
   ArrayCopy(VolArray, tick_volume);
   ArrayResize(OutArray, rates_total);
   ArrayInitialize(OutArray, 0);

   //--- 计算各个模型信号
   double modelBuffer[];
   ArraySetAsSeries(modelBuffer, false);
   ArrayResize(modelBuffer, rates_total);

   for(int model = 0; model <= 12; model++)
   {
      bool showSignal = false;
      switch(model)
      {
         case 0:  showSignal = Show_S0000; break;
         case 1:  showSignal = Show_S0001; break;
         case 2:  showSignal = Show_S0002; break;
         case 3:  showSignal = Show_S0003; break;
         case 4:  showSignal = Show_S0004; break;
         case 5:  showSignal = Show_S0005; break;
         case 6:  showSignal = Show_S0006; break;
         case 7:  showSignal = Show_S0007; break;
         case 8:  showSignal = Show_S0008; break;
         case 9:  showSignal = Show_S0009; break;
         case 10: showSignal = Show_S0010; break;
         case 11: showSignal = Show_S0011; break;
         case 12: showSignal = Show_S0012; break;
      }

      if(!showSignal)
         continue;

      ArrayInitialize(OutArray, 0);
      FQ_CLXS(rates_total, OutArray, HighArray, LowArray, OpenArray, CloseArray, VolArray,
              Wave_Opt, Stretch_Opt, Trend_Opt, model);

      //--- 绘制信号箭头
      for(int i = start; i < rates_total; i++)
      {
         double signal = OutArray[i];
         if(signal == 0)
            continue;

         string prefix = "FQCopilot_S" + IntegerToString(model, 4, '0') + "_";

         //--- 删除旧箭头
         ObjectDelete(0, prefix + IntegerToString(time[i]));

         //--- 买入信号（正值）
         if(signal > 0)
         {
            string arrowName = prefix + "BUY_" + IntegerToString(time[i]);
            if(ObjectCreate(0, arrowName, OBJ_ARROW_BUY, 0, time[i], low[i]))
            {
               ObjectSetInteger(0, arrowName, OBJPROP_COLOR, Buy_Color);
               ObjectSetInteger(0, arrowName, OBJPROP_WIDTH, Arrow_Size);
               ObjectSetDouble(0, arrowName, OBJPROP_PRICE, low[i]);
               ObjectSetInteger(0, arrowName, OBJPROP_TIME, time[i]);
            }
         }
         //--- 卖出信号（负值）
         else if(signal < 0)
         {
            string arrowName = prefix + "SELL_" + IntegerToString(time[i]);
            if(ObjectCreate(0, arrowName, OBJ_ARROW_SELL, 0, time[i], high[i]))
            {
               ObjectSetInteger(0, arrowName, OBJPROP_COLOR, Sell_Color);
               ObjectSetInteger(0, arrowName, OBJPROP_WIDTH, Arrow_Size);
               ObjectSetDouble(0, arrowName, OBJPROP_PRICE, high[i]);
               ObjectSetInteger(0, arrowName, OBJPROP_TIME, time[i]);
            }
         }

         //--- 保存到缓冲区
         switch(model)
         {
            case 0:  BufferS0000[i] = signal; break;
            case 1:  BufferS0001[i] = signal; break;
            case 2:  BufferS0002[i] = signal; break;
            case 3:  BufferS0003[i] = signal; break;
            case 4:  BufferS0004[i] = signal; break;
            case 5:  BufferS0005[i] = signal; break;
            case 6:  BufferS0006[i] = signal; break;
            case 7:  BufferS0007[i] = signal; break;
            case 8:  BufferS0008[i] = signal; break;
            case 9:  BufferS0009[i] = signal; break;
            case 10: BufferS0010[i] = signal; break;
            case 11: BufferS0011[i] = signal; break;
            case 12: BufferS0012[i] = signal; break;
         }
      }
   }

   return(rates_total);
}
//+------------------------------------------------------------------+
