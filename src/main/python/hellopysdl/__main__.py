from hellopysdl.service.MessageService import MessageService


def hello() -> None:
    print("hello python Standard Directory Layout")
    message_service: MessageService = MessageService()
    print(message_service.get_message("message.txt"))


if __name__ == '__main__':
    hello()
