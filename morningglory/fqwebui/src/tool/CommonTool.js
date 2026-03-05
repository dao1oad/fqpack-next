const CommonTool = {
  versions () {
    const u = navigator.userAgent
    return {
      trident: u.indexOf('Trident') > -1, // IE内核
      presto: u.indexOf('Presto') > -1, // opera内核
      webKit: u.indexOf('AppleWebKit') > -1, // 苹果、谷歌内核
      gecko: u.indexOf('Gecko') > -1 && u.indexOf('KHTML') === -1, // 火狐内核
      mobile: !!u.match(/AppleWebKit.*Mobile.*/), // 是否为移动终端
      ios: !!u.match(/\(i[^;]+;( U;)? CPU.+Mac OS X/), // 是否ios终端
      android: u.indexOf('Android') > -1 || u.indexOf('Adr') > -1, // 是否android终端
      iPhone: u.indexOf('iPhone') > -1, // 是否为iPhone或者QQHD浏览器
      iPad: u.indexOf('iPad') > -1, // 是否iPad
      safari: u.indexOf('Safari') === -1, // 是否web应该程序，没有头部与底部
      weixin: u.indexOf('MicroMessenger') > -1, // 是否微信
      qq: String(u.match(/\sqq/i)) === ' qq' // 是否QQ（QQ内置浏览器，空格加qq）
    }
  },
  copyToClipBoard (str) {
    const input = str
    const el = document.createElement('textarea')
    el.value = input
    el.setAttribute('readonly', '')
    // el.style.contain = 'strict';
    el.style.position = 'absolute'
    el.style.left = '-9999px'
    el.style.fontSize = '12pt' // Prevent zooming on iOS

    const selection = getSelection()
    let originalRange = null
    if (selection.rangeCount > 0) {
      originalRange = selection.getRangeAt(0)
    }
    document.body.appendChild(el)
    el.select()
    el.selectionStart = 0
    el.selectionEnd = input.length

    let success = false
    try {
      success = document.execCommand('copy')
    } catch (err) {
      //
    }

    document.body.removeChild(el)

    if (originalRange) {
      selection.removeAllRanges()
      selection.addRange(originalRange)
    }

    return success
  },
  dateFormat (fmt) {
    const o = {
      'M+': new Date().getMonth() + 1, // 月份
      'd+': new Date().getDate(), // 日
      'h+': new Date().getHours(), // 小时
      'm+': new Date().getMinutes(), // 分
      's+': new Date().getSeconds(), // 秒
      'q+': Math.floor((new Date().getMonth() + 3) / 3), // 季度
      S: new Date().getMilliseconds() // 毫秒
    }
    if (/(y+)/.test(fmt)) {
      fmt = fmt.replace(
        RegExp.$1,
        (new Date().getFullYear() + '').substr(4 - RegExp.$1.length)
      )
    }
    for (const k in o) {
      if (new RegExp('(' + k + ')').test(fmt)) {
        fmt = fmt.replace(
          RegExp.$1,
          RegExp.$1.length === 1
            ? o[k]
            : ('00' + o[k]).substr(('' + o[k]).length)
        )
      }
    }
    return fmt
  },
  // 给定时间字符串 转化为另一个格式
  formatDate (date, format) {
    if (!date) return
    if (!format) format = 'yyyy-MM-dd'
    switch (typeof date) {
      case 'string':
        date = new Date(date.replace(/-/, '/'))
        break
      case 'number':
        date = new Date(date)
        break
    }
    if (!(date instanceof Date)) return
    const dict = {
      yyyy: date.getFullYear(),
      M: date.getMonth() + 1,
      d: date.getDate(),
      H: date.getHours(),
      m: date.getMinutes(),
      s: date.getSeconds(),
      MM: ('' + (date.getMonth() + 101)).substr(1),
      dd: ('' + (date.getDate() + 100)).substr(1),
      HH: ('' + (date.getHours() + 100)).substr(1),
      mm: ('' + (date.getMinutes() + 100)).substr(1),
      ss: ('' + (date.getSeconds() + 100)).substr(1)
    }
    return format.replace(/(yyyy|MM?|dd?|HH?|ss?|mm?)/g, function () {
      return dict[arguments[0]]
    })
  },

  /**
   * Parse the time to string
   * @param {(Object|string|number)} time
   * @param {string} cFormat
   * @returns {string | null}
   */
  parseTime (time, cFormat) {
    if (arguments.length === 0) {
      return null
    }
    const format = cFormat || '{y}-{m}-{d} {h}:{i}:{s}'
    let date
    if (typeof time === 'object') {
      date = time
    } else {
      if (typeof time === 'string' && /^[0-9]+$/.test(time)) {
        time = parseInt(time)
      }
      if (typeof time === 'number' && time.toString().length === 10) {
        time = time * 1000
      }
      date = new Date(time)
    }
    const formatObj = {
      y: date.getFullYear(),
      m: date.getMonth() + 1,
      d: date.getDate(),
      h: date.getHours(),
      i: date.getMinutes(),
      s: date.getSeconds(),
      a: date.getDay()
    }
    const time_str = format.replace(/{([ymdhisa])+}/g, (result, key) => {
      const value = formatObj[key]
      // Note: getDay() returns 0 on Sunday
      if (key === 'a') {
        return ['日', '一', '二', '三', '四', '五', '六'][value]
      }
      return value.toString().padStart(2, '0')
    })
    return time_str
  },
  getParam (name) {
    let res = ''
    const categoryStr = window.location.href.split('?')[1] || ''
    if (categoryStr.length > 1) {
      const arr = categoryStr.split('&')
      for (let i = 0, len = arr.length; i < len; i++) {
        const pair = arr[i]
        const key = pair.split('=')[0]
        const value = pair.split('=')[1]

        if (key === name) {
          res = value
          console.log('coinName', res)
          break
        }
      }
    }
    return res
  }
}

export default CommonTool
