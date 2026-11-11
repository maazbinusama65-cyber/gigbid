function runSheets() {
  const sh = SpreadsheetApp.getActive().getSheetByName('Summary');
  const body = sh.getRange('A1:C10').getValues().map(r => r.join(' | ')).join('\n');
  MailApp.sendEmail('team@example.com', 'Weekly summary', body);
}
