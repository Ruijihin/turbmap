// 揺れやすさ地図の設定。
// dataBase: 地図データ(index.json と runs/)の置き場所。Workerで配信するときは 'data/' のまま。
// pirepUrl: 揺れの報告を返すGASのウェブアプリURL。空なら報告は表示しない(docs/pirep.md を参照)。
window.TURBMAP_CONFIG = {
  dataBase: 'data/',
  pirepUrl: ''
};
