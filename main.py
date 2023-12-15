from flask import Flask, request, make_response, render_template
import os
import openai
import requests
import csv
import datetime
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

# Initialize the S3 client
s3 = boto3.client('s3', aws_access_key_id=AWS_ACCESS_KEY, aws_secret_access_key=AWS_SECRET_KEY)

# Specify the file path
file_path = 'output.mp3'  # Replace with your file's path
file_name_in_bucket = 'outputtest.mp3'  # Replace with the desired file name in the bucket

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
    print(f"Extracted data: Phone number: {phone_number}, Author: {author_name}, Text: {submission_text}, Email: {author_email}")

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
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system",
             "content": "You have been tasked with writing a customized sales pitch, while sounding very candid and human. You will assume the fictional name of Tim. The text you generate will be turned into a phone call, so you must write out as if you are a human leaving a voicemail. You will be given the users information. Adapt this basic script..."},
            {"role": "user", "content": f"name: {author_name} reason for interest: {submission_text}"}
        ]
    )
    print("Received response from OpenAI.")

    # Processed text from OpenAI
    processed_text = response.choices[0].message.content
    print(response.choices[0].message.content)

    # Use ElevenLabs API to convert text to speech
    print("Sending request to ElevenLabs for text-to-speech.")

    # Specify the voice_id and other parameters
    voice_id = "xc4QPc6V39G77zvHrDEx"  # Replace with your chosen voice ID
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

    payload = {
        "model_id": "eleven_monolingual_v1",  # Replace with your model ID
        "text": processed_text,
        "voice_settings": {
            "similarity_boost": 0.5,  # Adjust as needed
            "stability": 0.5,  # Adjust as needed
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

    # Write the response to an MP3 file
    mp3_filename = 'output.mp3'
    with open(mp3_filename, 'wb') as f:
        for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
            if chunk:
                f.write(chunk)

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

    # Use Slybroadcast API to send voicemail
    print("Sending voicemail via Slybroadcast.")
    data = {
        'c_uid': slybroadcast_username,
        'c_password': slybroadcast_password,
        'c_url': file_url,
        'c_phone': phone_number,
        'c_callerID': '4849831138',
        'c_audio': 'mp3',
        'c_date': 'now',
    }
    response = requests.post('https://www.mobile-sphere.com/gateway/vmb.php', data=data)
    print("Voicemail sent via Slybroadcast.")
    print(f"Slybroadcast: {response}")

    # Record the successful submission
    submitted_phone_numbers.add(phone_number)
    timestamp = datetime.datetime.now()
    write_to_csv([timestamp, phone_number, author_name, submission_text, author_email, processed_text])
    print("Recorded submission details to CSV.")

    # Create a response and set a cookie indicating submission
    response = make_response({"status": "success"}, 200)
    response.set_cookie('submitted', 'true', max_age=60*60*24*30)  # Expires in 30 days
    print("Set cookie and prepared response.")

    return response

if __name__ == '__main__':
    app.run(debug=True)
