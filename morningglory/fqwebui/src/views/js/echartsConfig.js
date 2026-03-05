export default {
  bgColor: '#202529',
  upColor: 'red',
  upBorderColor: 'red',
  downColor: '#14d0cd',
  downBorderColor: '#14d0cd',

  higherUpColor: 'purple',
  higherDownColor: 'green',

  higherHigherUpColor: 'pink',
  higherHigherDownColor: 'blue',

  higherColor: '#14d0cd',
  higherHigherColor: 'green',
  dynamicOpertionColor: 'yellow',
  currentPriceColor: '#FFCDD2',
  macdUpLastValue: Number.MIN_SAFE_INTEGER,
  macdDownLastValue: Number.MAX_SAFE_INTEGER,

  bigMacdUpLastValue: Number.MIN_SAFE_INTEGER,
  bigMacdDownLastValue: Number.MAX_SAFE_INTEGER,

  macdUpDarkColor: '#EF5350',
  macdUpLightColor: '#FFCDD2',
  macdDownDarkColor: '#26A69A',
  macdDownLightColor: '#B2DFDB',
  loadingOption: {
    text: '让子弹飞一会...',
    maskColor: '#0B0E11',
    textColor: 'white',
    color: '#FFCC08'
  },
  // 多周期显示不下,需要配置
  multiPeriodGrid: [
    {
      left: '0%',
      right: '15%',
      top: 50,
      height: '85%'
    }
  ],
  klineBigGrid: [
    {
      // 直角坐标系
      left: '0%',
      right: '10%',
      top: 50,
      height: '85%'
    },
    {
      top: '65%',
      height: '20%',
      left: '0%',
      right: '10%'
    }
  ]
}
