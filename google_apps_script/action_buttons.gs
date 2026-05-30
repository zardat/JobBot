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


function onEdit(e) {
  var sheet = e.source.getActiveSheet();
  if (sheet.getName() !== SHEET_NAME) return;

  var row = e.range.getRow();
  var col = e.range.getColumn();

  if (col !== COL.SEND_EMAIL || row <= 1) return;
  if (e.value !== "TRUE") return;

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
    SpreadsheetApp.getUi().alert("No contact email in row " + row + ". Skipping.");
    return;
  }

  if (status === "Emailed") {
    SpreadsheetApp.getUi().alert("Email already sent for " + company + " — " + role);
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
