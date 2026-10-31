"""Print the deploy target from settings as shell assignments (read by scripts/_cdk.sh).

Keeps the profile/region logic in one place instead of duplicating it in bash.
"""

import shlex

from rail_rights_agent.settings import load_settings


def main() -> None:
    settings = load_settings()
    print(f"RAILAGENT_AWS_PROFILE={shlex.quote(settings.aws_profile)}")
    print(f"RAILAGENT_AWS_REGION={shlex.quote(settings.aws_region)}")


if __name__ == "__main__":
    main()
