/**
 * 揺れの報告(PIREP)を Googleフォームで集め、地図に重ねるための JSON を返す。
 * 使い方は docs/pirep.md を参照。
 *
 * 1. スプレッドシートを新規作成し、[拡張機能]→[Apps Script] にこのファイルを貼る
 * 2. setup() を1回実行する(フォームが作られ、回答がこのシートに入るようになる)
 * 3. [デプロイ]→[新しいデプロイ]→種類「ウェブアプリ」、アクセスできるユーザー「全員」
 * 4. 表示されたURLを web/config.js の pirepUrl に書く
 */

var DAYS = 7; // 何日前までの報告を返すか

function setup() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var form = FormApp.create('揺れの報告');
  form.setDescription('揺れやすさ地図の精度確認に使います。位置は緯度・経度(10進数)で入力してください。');
  form.addDateTimeItem().setTitle('日時(日本時間)').setRequired(true);
  form.addTextItem().setTitle('緯度(例 35.6)').setRequired(true)
    .setValidation(FormApp.createTextValidation().requireNumberBetween(20, 50).build());
  form.addTextItem().setTitle('経度(例 139.8)').setRequired(true)
    .setValidation(FormApp.createTextValidation().requireNumberBetween(115, 155).build());
  form.addTextItem().setTitle('高度 FL(例 280)').setRequired(true)
    .setValidation(FormApp.createTextValidation().requireNumberBetween(0, 500).build());
  form.addMultipleChoiceItem().setTitle('強さ').setChoiceValues(['LGT', 'MOD', 'SEV']).setRequired(true);
  form.addMultipleChoiceItem().setTitle('雲の中').setChoiceValues(['いいえ', 'はい', '不明']);
  form.addParagraphTextItem().setTitle('備考');
  form.setDestination(FormApp.DestinationType.SPREADSHEET, ss.getId());
  Logger.log('フォームの回答用URL: ' + form.getPublishedUrl());
}

function doGet() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheets().filter(function (s) { return s.getFormUrl(); })[0];
  var out = [];
  if (sheet) {
    var rows = sheet.getDataRange().getValues();
    var head = rows.shift();
    var col = function (prefix) { return head.findIndex(function (h) { return String(h).indexOf(prefix) === 0; }); };
    var cT = col('日時'), cLa = col('緯度'), cLo = col('経度'), cF = col('高度'), cS = col('強さ'), cC = col('雲の中');
    var since = Date.now() - DAYS * 86400e3;
    rows.forEach(function (r) {
      var t = r[cT] instanceof Date ? r[cT] : new Date(r[cT]);
      if (!(t.getTime() >= since)) return;
      out.push({
        time: t.toISOString(),             // スプレッドシートのタイムゾーン(日本時間)で解釈された日時
        lat: Number(r[cLa]), lon: Number(r[cLo]), fl: Number(r[cF]),
        severity: String(r[cS]), in_cloud: cC >= 0 ? String(r[cC]) : ''
      });
    });
  }
  return ContentService.createTextOutput(JSON.stringify({ updated: new Date().toISOString(), reports: out }))
    .setMimeType(ContentService.MimeType.JSON);
}
