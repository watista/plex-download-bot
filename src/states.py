#!/usr/bin/python3

# Define chat states
VERIFY, REQUEST_ACCOUNT, REQUEST_ACCOUNT_EMAIL, REQUEST_ACCOUNT_PHONE, REQUEST_ACCOUNT_REFER, REQUEST_MOVIE, REQUEST_SERIE, VERIFY_PWD, MOVIE_OPTION, MOVIE_NOTIFY, SERIE_OPTION, SERIE_NOTIFY, MOVIE_UPGRADE, SERIE_UPGRADE, MOVIE_UPGRADE_INFO, SERIE_UPGRADE_INFO, SERIE_UPGRADE_OPTION, HELP_CHOICE, HELP_OTHER, MESSAGE_ID, MESSAGE_MESSAGE, REQUEST_AGAIN, MESSAGE_ALL_ID, AFMELDEN_OPTIE, AANMELD_OPTIE, AANMELD_CHOICE, AANMELDEN_SERIE, ADD_MOVIE, ADD_MOVIE_USER, MOVIE_UPGRADE_INFO_OTHER = range(30)

# The step of a Gesprek in a line: the name of its state in lower case, like verify_pwd
STEPS = {state: name.lower() for name, state in list(globals().items()) if name.isupper() and isinstance(state, int)}


def step_name(state: object) -> str | None:
    """ The name of a state in a line, None outside a Gesprek """
    if state is None:
        return None
    return STEPS.get(state, str(state))
