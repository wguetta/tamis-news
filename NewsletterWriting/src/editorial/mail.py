import os
import html
import smtplib

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def smtp_settings() -> dict:
    return {
        "host": os.environ["SMTP_HOST"],
        "port": int(os.environ["SMTP_PORT"]),
        "username": os.environ["SMTP_USERNAME"],
        "password": os.environ["SMTP_PASSWORD"],
        "from_email": os.environ["FROM_EMAIL"],
    }


# ============================================================
# HTML HELPERS
# ============================================================

def escape(text):
    """Safely escape text before putting it into HTML."""
    return html.escape(str(text))


def render_story(story, number=None):
    """
    Render one story.

    Expected format:
    {
        "title": "...",
        "details": "..."
    }
    """

    number_html = ""

    if number is not None:
        number_html = f"""
        <div class="story-number">
            {number}
        </div>
        """

    return f"""
    <tr>
        <td class="story">

            {number_html}

            <div class="story-content">

                <div class="story-title">
                    {escape(story["title"])}
                </div>

                <div class="story-details">
                    {escape(story["details"])}
                </div>

            </div>

        </td>
    </tr>
    """


# ============================================================
# NEWSLETTER HTML
# ============================================================

def generate_newsletter_html(newsletter):
    """
    Generate the complete HTML newsletter.

    Expected structure:

    newsletter = {
        "main": {
            "title": "...",
            "body": "..."
        },

        "headlines": [
            {
                "title": "...",
                "details": "..."
            },
            ...
        ],

        "stories_to_watch": [
            {
                "title": "...",
                "details": "..."
            },
            ...
        ]
    }
    """

    # --------------------------------------------------------
    # Main section
    # --------------------------------------------------------

    main = newsletter["main"]

    main_html = f"""
    <div class="main-title">
        {escape(main["title"])}
    </div>

    <div class="main-body">
        {escape(main["body"])}
    </div>
    """

    # --------------------------------------------------------
    # Headlines
    # --------------------------------------------------------

    headlines = newsletter["headlines"]

    if len(headlines) != 3:
        raise ValueError(
            "The headlines section must contain exactly 3 headlines."
        )

    headlines_html = ""

    for i, headline in enumerate(headlines, start=1):
        headlines_html += render_story(
            headline,
            number=i
        )

    # --------------------------------------------------------
    # Stories to watch
    # --------------------------------------------------------

    stories_to_watch = newsletter["stories_to_watch"]

    if len(stories_to_watch) != 3:
        raise ValueError(
            "The stories_to_watch section must contain exactly 3 stories."
        )

    stories_html = ""

    for i, story in enumerate(stories_to_watch, start=1):
        stories_html += render_story(
            story,
            number=i
        )

    # --------------------------------------------------------
    # Complete HTML
    # --------------------------------------------------------

    return f"""
<!DOCTYPE html>

<html>

<head>

    <meta charset="UTF-8">

    <meta name="viewport"
          content="width=device-width, initial-scale=1.0">

    <!-- Tell email clients that both modes are supported -->
    <meta name="color-scheme"
          content="light dark">

    <meta name="supported-color-schemes"
          content="light dark">

    <style>

        /* ====================================================
           COLOR VARIABLES
           ==================================================== */

        :root {{
            color-scheme: light dark;
        }}


        /* ====================================================
           BASE
           ==================================================== */

        body {{
            margin: 0;
            padding: 0;
            width: 100%;
            background-color: #f4f1ea;
            color: #111111;
            font-family:
                Arial,
                Helvetica,
                sans-serif;
        }}

        table {{
            border-spacing: 0;
        }}

        td {{
            padding: 0;
        }}


        /* ====================================================
           MAIN CONTAINER
           ==================================================== */

        .outer-container {{
            width: 100%;
            background-color: #f4f1ea;
        }}

        .newsletter {{
            width: 620px;
            max-width: 620px;
            background-color: #ffffff;
        }}


        /* ====================================================
           TOP ACCENT
           ==================================================== */

        .accent {{
            height: 7px;
            background-color: #ff5a36;
            font-size: 0;
            line-height: 0;
        }}


        /* ====================================================
           MAIN SECTION
           ==================================================== */

        .main-section {{
            padding: 35px 38px 38px 38px;
        }}

        .main-label {{
            font-size: 12px;
            line-height: 1.2;
            font-weight: 800;
            letter-spacing: 1.5px;
            text-transform: uppercase;
            color: #ff5a36;
            margin-bottom: 10px;
        }}

        .main-title {{
            font-size: 34px;
            line-height: 1.08;
            font-weight: 900;
            color: #111111;
            margin-bottom: 18px;
        }}

        .main-body {{
            font-size: 17px;
            line-height: 1.6;
            color: #444444;
        }}


        /* ====================================================
           SECTION HEADERS
           ==================================================== */

        .section {{
            padding: 0 38px 38px 38px;
        }}

        .section-header {{
            border-top: 3px solid #111111;
            padding-top: 14px;
            margin-bottom: 22px;
        }}

        .section-title {{
            font-size: 22px;
            line-height: 1.2;
            font-weight: 900;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: #111111;
        }}


        /* ====================================================
           STORIES
           ==================================================== */

        .story {{
            padding: 0 0 22px 0;
            border-bottom: 1px solid #dddddd;
        }}

        .story-number {{
            float: left;
            width: 30px;
            height: 30px;
            margin-right: 13px;

            background-color: #111111;
            color: #ffffff;

            font-size: 14px;
            line-height: 30px;
            font-weight: 800;
            text-align: center;
        }}

        .story-content {{
            overflow: hidden;
        }}

        .story-title {{
            font-size: 19px;
            line-height: 1.3;
            font-weight: 800;
            color: #111111;
            margin-bottom: 6px;
        }}

        .story-details {{
            font-size: 15px;
            line-height: 1.55;
            color: #555555;
        }}


        /* ====================================================
           SPACING BETWEEN STORIES
           ==================================================== */

        .story-spacer {{
            height: 20px;
        }}


        /* ====================================================
           FOOTER
           ==================================================== */

        .footer {{
            padding: 24px 38px;
            background-color: #111111;
        }}

        .footer-text {{
            font-size: 12px;
            line-height: 1.5;
            color: #aaaaaa;
        }}


        /* ====================================================
           MOBILE
           ==================================================== */

        @media only screen and (max-width: 650px) {{

            .newsletter {{
                width: 100% !important;
                max-width: 100% !important;
            }}

            .main-section {{
                padding: 28px 24px 32px 24px !important;
            }}

            .section {{
                padding-left: 24px !important;
                padding-right: 24px !important;
            }}

            .main-title {{
                font-size: 29px !important;
            }}

            .main-body {{
                font-size: 16px !important;
            }}

            .story-title {{
                font-size: 18px !important;
            }}

        }}


        /* ====================================================
           DARK MODE
           ==================================================== */

        @media (prefers-color-scheme: dark) {{

            body {{
                background-color: #171717 !important;
                color: #eeeeee !important;
            }}

            .outer-container {{
                background-color: #171717 !important;
            }}

            .newsletter {{
                background-color: #242424 !important;
            }}

            .main-title,
            .section-title,
            .story-title {{
                color: #f5f5f5 !important;
            }}

            .main-body,
            .story-details {{
                color: #cccccc !important;
            }}

            .section-header {{
                border-color: #eeeeee !important;
            }}

            .story {{
                border-color: #444444 !important;
            }}

            .story-number {{
                background-color: #eeeeee !important;
                color: #111111 !important;
            }}

        }}

    </style>

</head>


<body>

<table
    class="outer-container"
    width="100%"
    cellpadding="0"
    cellspacing="0"
    border="0"
>

    <tr>

        <td align="center" style="padding: 30px 12px;">

            <table
                class="newsletter"
                width="620"
                cellpadding="0"
                cellspacing="0"
                border="0"
            >

                <!-- =========================================
                     TOP ACCENT
                     ========================================= -->

                <tr>
                    <td class="accent"></td>
                </tr>


                <!-- =========================================
                     MAIN SECTION
                     ========================================= -->

                <tr>

                    <td class="main-section">

                        <div class="main-label">
                            THE BIG PICTURE
                        </div>

                        {main_html}

                    </td>

                </tr>


                <!-- =========================================
                     HEADLINES
                     ========================================= -->

                <tr>

                    <td class="section">

                        <div class="section-header">

                            <div class="section-title">
                                Headlines
                            </div>

                        </div>


                        <table
                            width="100%"
                            cellpadding="0"
                            cellspacing="0"
                            border="0"
                        >

                            {headlines_html}

                        </table>

                    </td>

                </tr>


                <!-- =========================================
                     STORIES TO WATCH
                     ========================================= -->

                <tr>

                    <td class="section">

                        <div class="section-header">

                            <div class="section-title">
                                Stories to Watch
                            </div>

                        </div>


                        <table
                            width="100%"
                            cellpadding="0"
                            cellspacing="0"
                            border="0"
                        >

                            {stories_html}

                        </table>

                    </td>

                </tr>


                <!-- =========================================
                     FOOTER
                     ========================================= -->

                <tr>

                    <td class="footer">

                        <div class="footer-text">
                            Your personalized daily news briefing.
                        </div>

                    </td>

                </tr>

            </table>

        </td>

    </tr>

</table>

</body>

</html>
"""


# ============================================================
# PLAIN TEXT VERSION
# ============================================================

def generate_plain_text(newsletter):
    """
    Generate a plain-text fallback version of the newsletter.
    """

    lines = []

    # Main
    lines.append("THE BIG PICTURE")
    lines.append("")
    lines.append(newsletter["main"]["title"])
    lines.append("")
    lines.append(newsletter["main"]["body"])
    lines.append("")

    # Headlines
    lines.append("====================")
    lines.append("HEADLINES")
    lines.append("====================")
    lines.append("")

    for i, headline in enumerate(
        newsletter["headlines"],
        start=1
    ):
        lines.append(
            f"{i}. {headline['title']}"
        )
        lines.append(
            headline["details"]
        )
        lines.append("")

    # Stories to watch
    lines.append("====================")
    lines.append("STORIES TO WATCH")
    lines.append("====================")
    lines.append("")

    for i, story in enumerate(
        newsletter["stories_to_watch"],
        start=1
    ):
        lines.append(
            f"{i}. {story['title']}"
        )
        lines.append(
            story["details"]
        )
        lines.append("")

    return "\n".join(lines)


# ============================================================
# SEND EMAIL
# ============================================================

def send_newsletter(
    recipient,
    subject,
    newsletter
):
    """
    Generate and send the newsletter through Gmail SMTP.
    """

    html_content = generate_newsletter_html(newsletter)
    plain_text = generate_plain_text(newsletter)

    smtp = smtp_settings()
    message = MIMEMultipart("alternative")

    message["Subject"] = subject
    message["From"] = smtp["from_email"]
    message["To"] = recipient

    # Plain-text fallback
    message.attach(
        MIMEText(
            plain_text,
            "plain",
            "utf-8"
        )
    )

    # HTML version
    message.attach(
        MIMEText(
            html_content,
            "html",
            "utf-8"
        )
    )

    # Connect to Gmail
    with smtplib.SMTP(
        smtp["host"],
        smtp["port"]
    ) as server:

        server.starttls()

        server.login(
            smtp["username"],
            smtp["password"]
        )

        server.sendmail(
            smtp["from_email"],
            recipient,
            message.as_string()
        )

    print(
        f"Newsletter successfully sent to {recipient}"
    )


def email_payload(newsletter: dict) -> dict:
    """Map a written newsletter onto the email template fields."""
    return {
        "main": {
            "title": newsletter["main_section"]["title"],
            "body": newsletter["main_section"]["body"],
        },
        "headlines": [
            {"title": item["headline"], "details": item["details"]}
            for item in newsletter["headlines"]["headlines"]
        ],
        "stories_to_watch": [
            {"title": item["headline"], "details": item["watch_for"]}
            for item in newsletter["stories_to_watch"]["stories_to_watch"]
        ],
    }


def send_reader_newsletter(newsletter: dict, subject: str = "Your Daily Briefing") -> None:
    send_newsletter(
        recipient=newsletter["email"],
        subject=subject,
        newsletter=email_payload(newsletter),
    )


