// Column index map (1-based)
var COL = {
  COMPANY:        4,   // D
  ROLE:           5,   // E
  CONTACT_NAME:   11,  // K
  CONTACT_EMAIL:  13,  // M
  RESUME_LINK:    15,  // O
  EMAIL_SUBJECT:  16,  // P
  EMAIL_BODY:     17,  // Q
  STATUS:         20,  // T
  DATE_APPLIED:   21,  // U
  SEND_EMAIL:     23,  // W  ← checkbox
};

var SHEET_NAME = "action_sheet";
var SENDER_NAME = "Parth Joshi";


// Attach this to an INSTALLABLE "On edit" trigger (Triggers → Add Trigger →
// function: handleEdit, source: From spreadsheet, event: On edit). An
// installable trigger runs with full authorization, which the simple onEdit
// sandbox does not — required for GmailApp / DriveApp here.
function handleEdit(e) {
  // The trigger only passes `e` on a real cell edit. Clicking "Run" in the
  // editor calls it with no event object, which throws
  // "Cannot read properties of undefined (reading 'source')". Guard against it.
  if (!e || !e.source || !e.range) return;

  var sheet = e.range.getSheet();
  Logger.log("handleEdit fired: sheet=%s row=%s col=%s value=%s",
             sheet.getName(), e.range.getRow(), e.range.getColumn(), e.value);
  if (sheet.getName() !== SHEET_NAME) return;

  var row = e.range.getRow();
  var col = e.range.getColumn();

  if (col !== COL.SEND_EMAIL || row <= 1) return;

  // Checkbox edits report the value as boolean `true` (installable trigger) or
  // the string "TRUE" (simple trigger) — accept either.
  var checked = (e.value === true || String(e.value).toUpperCase() === "TRUE");
  if (!checked) return;

  // Uncheck immediately so double-sends can't happen
  e.range.setValue(false);

  var data = sheet.getRange(row, 1, 1, COL.SEND_EMAIL).getValues()[0];

  var contactEmail = data[COL.CONTACT_EMAIL - 1];
  var emailSubject = data[COL.EMAIL_SUBJECT - 1];
  var emailBody    = data[COL.EMAIL_BODY - 1];
  var resumeLink   = data[COL.RESUME_LINK - 1];
  var status       = data[COL.STATUS - 1];
  var company      = data[COL.COMPANY - 1];
  var role         = data[COL.ROLE - 1];

  if (!contactEmail) {
    SpreadsheetApp.getActiveSpreadsheet().toast("No contact email in row " + row + ". Skipping.", "JobBot", 5);
    return;
  }

  if (status === "Emailed") {
    SpreadsheetApp.getActiveSpreadsheet().toast("Already emailed: " + company + " — " + role, "JobBot", 5);
    return;
  }

  // Attach resume PDF from Drive if link exists
  var attachments = [];
  var match = resumeLink ? resumeLink.match(/\/d\/([a-zA-Z0-9_-]+)/) : null;
  if (match) {
    try {
      var file = DriveApp.getFileById(match[1]);
      attachments.push(file.getAs(MimeType.PDF));
    } catch (err) {
      Logger.log("Could not fetch resume PDF: " + err);
    }
  }

  // Send the email
  GmailApp.sendEmail(contactEmail, emailSubject, emailBody, {
    name: SENDER_NAME,
    attachments: attachments,
  });

  // Update status + timestamp
  sheet.getRange(row, COL.STATUS).setValue("Emailed");
  sheet.getRange(row, COL.DATE_APPLIED).setValue(
    Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "yyyy-MM-dd")
  );

  Logger.log("Email sent: " + company + " — " + role + " → " + contactEmail);
}
