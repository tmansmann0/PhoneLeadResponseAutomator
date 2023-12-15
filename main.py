from flask import Flask, request, make_response, render_template
import os
import openai
import requests
import csv
from datetime import datetime, timedelta
import dotenv
import boto3
from botocore.exceptions import NoCredentialsError

app = Flask(__name__)

from dotenv import load_dotenv
load_dotenv()  # This line loads the variables from .env

# Load API keys from environment variables
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
ELEVENLABS_API_KEY = os.getenv('ELEVENLABS_API_KEY')
slybroadcast_username = os.getenv('slybroadcast_username')
slybroadcast_password = os.getenv('slybroadcast_password')
AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY")
AWS_SECRET_KEY = os.getenv("AWS_SECRET_KEY")
BUCKET_NAME = os.getenv("BUCKET_NAME")

CHUNK_SIZE = 1024

# Caller ID options (4849831138 or 8148261207
caller_id = '8148261207'

# Initialize the S3 client
s3 = boto3.client('s3', aws_access_key_id=AWS_ACCESS_KEY, aws_secret_access_key=AWS_SECRET_KEY)

# Specify the file path
file_path = 'output.mp3'  # Replace with your file's path
file_name_in_bucket = 'output.mp3'  # Replace with the desired file name in the bucket

# Initialize OpenAI API
openai.api_key = OPENAI_API_KEY

submitted_phone_numbers = set()

def write_to_csv(data):
    with open('submissions.csv', 'a', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(data)

@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')

@app.route('/process', methods=['POST'])
def process_text():
    print("Received request for processing text.")

    # Extracting multiple inputs from the request
    data = request.form
    phone_number = data.get('phone_number')
    author_name = data.get('author_name')
    submission_text = data.get('submission_text')
    author_email = data.get('author_email')
    sales_script = data.get('sales_script')
    gpt_setting = data.get('gpt_setting')
    speaker_voice = data.get('speaker_voice')
    print(f"Extracted data: Phone number: {phone_number}, Author: {author_name}, Text: {submission_text}, Email: {author_email}")
    print(f"Sales Script: {sales_script}")
    print(f"GPT settings: {gpt_setting}")
    print(f"Speaker voice: {speaker_voice}")
    # Check for cookie to see if user has already submitted
    #user_cookie = request.cookies.get('submitted')
    ##if user_cookie:
        ##print("User has already submitted.")
        ##return {"error": "You have already submitted."}, 400

    # Check if phone number has already submitted
    ##if phone_number in submitted_phone_numbers:
        ##print(f"Phone number {phone_number} has already made a submission.")
        ##return {"error": "This phone number has already made a submission."}, 400

    # Limiting submission text size
    if len(submission_text) > 6000:
        print("Submission text is too long.")
        return {"error": "Submission text is too long"}, 400

    # Processing text with OpenAI
    print("Sending request to OpenAI.")
    response = openai.chat.completions.create(
        model=gpt_setting,
        temperature=0.2,
        messages=[
            {"role": "system",
             "content": f"{sales_script}"},
            {"role": "user", "content": f"name: {author_name} reason for interest: {submission_text}"}
        ]
    )
    print("Received response from OpenAI.")

    # Processed text from OpenAI
    processed_text = str(response.choices[0].message.content)
    print(response.choices[0].message.content)

    # Use ElevenLabs API to convert text to speech
    print("Sending request to ElevenLabs for text-to-speech.")

    # Specify the voice_id and other parameters
    voice_id = speaker_voice  # Replace with your chosen voice ID
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

    payload = {
        "model_id": "eleven_multilingual_v2",  # Replace with your model ID
        "text": processed_text,
        "voice_settings": {
            "similarity_boost": 0.8,  # Adjust as needed
            "stability": 0.7,  # Adjust as needed
            "style": 0.3,  # Adjust as needed
            "use_speaker_boost": True
        }
    }
    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": ELEVENLABS_API_KEY
    }
    response = requests.post(url, json=payload, headers=headers)

    # Define Filename
    mp3_temp_filename = 'tempoutput.mp3'
    mp3_filename = 'output.mp3'
    # Delete existing file
    if os.path.exists(mp3_filename):
        os.remove(mp3_filename)
    # Write the response to an MP3 file
    with open(mp3_temp_filename, 'wb') as f:
        for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
            if chunk:
                f.write(chunk)

    # Rename the temporary file to the actual file name after the download is complete
    os.rename(mp3_temp_filename, mp3_filename)

    try:
        # Upload the file
        s3.upload_file(file_path, BUCKET_NAME, file_name_in_bucket)
        print(f"Upload Successful. File uploaded to {BUCKET_NAME}/{file_name_in_bucket}")
    except FileNotFoundError:
        print("The file was not found")
    except NoCredentialsError:
        print("Credentials not available")
    # If you need the file's URL:
    file_url = f"https://{BUCKET_NAME}.s3.amazonaws.com/{file_name_in_bucket}"
    print(f'file stored at {file_url}')

    # Current time
    current_time_et = datetime.now()

    # Setting the delivery time to 2 minutes in the future
    future_time_et = current_time_et + timedelta(minutes=2)

    # Formatting the future time in the required format
    formatted_future_time = future_time_et.strftime('%Y-%m-%d %H:%M:%S')

    # Use Slybroadcast API to send voicemail
    print("Sending voicemail via Slybroadcast.")
    data = {
        'c_uid': slybroadcast_username,
        'c_password': slybroadcast_password,
        'c_url': file_url,
        'c_phone': phone_number,
        'c_callerID': caller_id,
        'c_audio': 'Mp3',
        'c_date': formatted_future_time,
        'c_title': 'test_campaign',
    }
    response = requests.post('https://www.mobile-sphere.com/gateway/vmb.php', data=data)
    print("Voicemail sent via Slybroadcast.")
    print(response.text)

    # Record the successful submission
    submitted_phone_numbers.add(phone_number)
    timestamp = datetime.now()
    write_to_csv([timestamp, phone_number, author_name, submission_text, author_email, processed_text])
    print("Recorded submission details to CSV.")

    # Create a response and set a cookie indicating submission
    response = make_response({"status": "success"}, 200)
    response.set_cookie('submitted', 'true', max_age=60*60*24*30)  # Expires in 30 days
    print("Set cookie and prepared response.")

    return response

if __name__ == '__main__':
    app.run(debug=True)
