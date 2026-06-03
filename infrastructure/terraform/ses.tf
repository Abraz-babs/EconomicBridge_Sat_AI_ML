# EconomicBridge — SES sender identity for tenant invite/activation emails.
#
# Created only when var.ses_sender_email is set; otherwise the API runs with
# EMAIL_BACKEND=console (logs the activation link instead of emailing it), so a
# first deploy without SES configured still works.
#
# An EMAIL identity (not a domain identity) is used for simplicity: after apply,
# AWS sends a verification link to the address — click it before invites can
# send. A new SES account is also in the sandbox (can only send to verified
# recipients) until you request production access. For a real launch, switch to
# a domain identity + DKIM and request sandbox removal (see README).

resource "aws_ses_email_identity" "sender" {
  count = var.ses_sender_email != "" ? 1 : 0
  email = var.ses_sender_email
}
