// 外框（頁首、全域錯誤訊息）的共用狀態。對應 Alpha 的 currentHeader 與 error。
import { reactive } from 'vue';

export const shell = reactive({
  header: { kicker: '', title: '', subtitle: '', phase: '' },
  error: '',
  navClicks: 0 // 左側選單被點的次數（在同一頁再點一次時，讓頁面回到起始畫面）
});

export function setHeader(header) {
  shell.header = { kicker: '', title: '', subtitle: '', phase: '', ...header };
}
