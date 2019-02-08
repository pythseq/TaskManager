from modules.Notifier import Notifier


def main():
    recipient = "rlorigro@ucsc.edu"
    sender = "rlorigro@ucsc.edu"

    notifier = Notifier(email_recipient=recipient, email_sender=sender)

    subject = "Test"
    body = "success"
    notifier.generate_message(subject, body)
    notifier.send_message()


if __name__ == "__main__":
    main()
