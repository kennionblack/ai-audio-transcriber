from runtime_events import emit_event


def talk_to_user(message: str) -> str:
    """Send a message to the user and get the user's response.

    This is the ONLY way to communicate with the user,
    so all information to and from the user will come through this function.
    """
    # Tell Gradio that the agent is about to wait for user input.
    # Gradio sees this and sends the automatic reply.
    emit_event("user_message", message=message)
    print()
    print("AI: ", message)
    return input("User: ")

