import os
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain.prompts import PromptTemplate
from langchain_google_genai import GoogleGenerativeAI
from langchain_core.output_parsers import BaseLLMOutputParser 
from langchain_core.messages import HumanMessage ,AIMessage
from langchain_core.exceptions import OutputParserException
from sentence_transformers import CrossEncoder
from dotenv import load_dotenv, find_dotenv
from langchain.tools import tool
from langchain.agents import AgentExecutor, create_react_agent, create_structured_chat_agent
from langchain import hub
from langchain_core.messages import SystemMessage
from datetime import date
from langchain.memory import  ConversationSummaryBufferMemory
import requests
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import shutil
from google.cloud import storage
import warnings



warnings.filterwarnings("ignore")

GCP_BUCKET_NAME = "bookiebee_encoded"  

PERSIST_DIR = "./vectorstorage"

# Initialize embeddings model
embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
#Encoder for re-rankingg
cross_encoder = CrossEncoder("cross-encoder/ms-marco-TinyBERT-L-6") 
 # Global retriever variable to be set after loading the vector store
retriever = None 

#This model will be used for query expannsion and summarizing chat history in memory buffer
questions_generator = GoogleGenerativeAI(
    model="gemini-1.5-pro",
    google_api_key="AIzaSyDvbke4TODM1nOMbkZAXXhOVGQeECSsATU",
    safety_settings={
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_ONLY_HIGH,
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_ONLY_HIGH},
    temperature=0,
    max_tokens=1000,
    model_kwargs={"top_p": 1.0, "top_k": 6, "presence_penalty": 0.5, "frequency_penalty": 0.5} 
)


#Prompt Template for query expansion
QUERY_PROMPT = PromptTemplate(
    input_variables=["question"],
    template="""You are an AI assistant. Generate seven variations of the user question from several different perspectives for document retrieval. 
    The questions should be pin-pointing such that they can be answered out of a mass of similar documents. 
    Scenario :
    Original Question : "XYZ's Contact number needed"
        >>>  There are several similar documents of information in the database but only one of them might accurately answer this question.
        >>>  Thus make sure the questions derived focus on the exact original question from mutliple question so that one piece of information that is needed to answer the original question accurately can be found.
    Original question: {question}"""
)



# Define custom output parser
class LineListOutputParser(BaseLLMOutputParser):
    def parse(self, text: str) -> list[str]:
        try:
            return [line.strip() for line in text.strip().split("\n") if line.strip()]
        except Exception as e:
            raise OutputParserException(f"Failed to parse output: {text}") from e

    def parse_result(self, result) -> list[str]:
        if isinstance(result, list) and all(hasattr(item, "text") for item in result):
            text_output = "\n".join([item.text for item in result])
            return self.parse(text_output)
        return self.parse(result)

output_parser = LineListOutputParser()


def download_from_gcp_bucket(bucket_name, destination_dir, folder_name="chroma_db"):
    """Downloads the contents of a specific folder in a GCP bucket to a local directory."""
    client = storage.Client()
    bucket = client.bucket(bucket_name)

    # Prefix for the folder in the bucket
    folder_prefix = f"{folder_name}/"  # Ensure the folder ends with a "/"

    blobs = bucket.list_blobs(prefix=folder_prefix)

    # Ensure the destination directory exists
    os.makedirs(destination_dir, exist_ok=True)

    for blob in blobs:
        # Local path where the file will be saved
        local_path = os.path.join(destination_dir, blob.name)

        # Create the subdirectory if it does not exist
        os.makedirs(os.path.dirname(local_path), exist_ok=True)

        # Download the file
        print(f"Downloading {local_path}")
        blob.download_to_filename(local_path)



def remove_temp_directory(directory):
    """Removes a temporary directory."""
    if os.path.exists(directory):
        shutil.rmtree(directory)
        print(f"Temporary directory {directory} removed.")


def load_vector_store():
    """Loads Chroma vector store from the temporary directory."""
    print(f"Loading ChromaDB from {PERSIST_DIR}")
    db = Chroma(
        embedding_function=embeddings,
        persist_directory="./vectorstorage/chroma_db")
    
    global retriever
    retriever = db.as_retriever(search_kwargs={"k": 6})
    print(f"Vector store loaded with retriever.")
    return db , retriever




memory = ConversationSummaryBufferMemory(llm=questions_generator ,
                                         memory_key="chat_history" ,
                                         return_messages=True
                                         ) 


# Initialize embeddings model
embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")

# This is for the Agent's Decision making 
reasoning_engine = GoogleGenerativeAI(
    model="gemini-1.5-pro",
    google_api_key="AIzaSyDvbke4TODM1nOMbkZAXXhOVGQeECSsATU",
    safety_settings={
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_ONLY_HIGH,
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_ONLY_HIGH},
    temperature=0.3,
    max_tokens=10000,
    model_kwargs={"top_p": 1.0, "top_k": 2, "presence_penalty": 0, "frequency_penalty": 0} ,
    system_message = SystemMessage(
    """
        Generate JSON responses only in the following format :
       ```
       { 
       "action": <TOOL>, 
       "action_input": "<Your response here>" 
       } 

       ```
    """
     )
    
)

# Initialize CrossEncoder for re-ranking
cross_encoder = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')

# Define the main function for querying

@tool
def staticTool(query):
    """
    This tool will bring information related to:
    >>> Up-to-date rules & policies of Bookme.Pk
    >>> Promotions and Offers
    >>> Newly introduced features in Bookme's Application and Website
    >>> Information regarding various vendors, operators, partners of Bookme.Pk
    >>> Information Regarding all services at Bookme.Pk (Events, Movies, Hotel & Travel Bookings etc)
    >>> Rules and regulations regarding any service (Events, Movies, Hotel & Travel Bookings etc)

    USAGE GUIDELINES :
    >>> Avoid using the staticTool if query expansion or retrieval logic adds unnecessary overhead (e.g., for simple queries).
    >>> Use the returned list of documents to formulate the most appropriate response for the user's query.
    >>> Do not call this tool multiples times.
    """
    # Generate expanded queries using GoogleGenerativeAI
    response = (QUERY_PROMPT | questions_generator).invoke({"question": query})
    expanded_queries = output_parser.parse(response)


    print("\n _______FORMULATED QUESTIONS_________\n")
    for formulated_question in expanded_queries:
        print(formulated_question, '\n')

    # Retrieve relevant documents for each formulated question
    retrieved_docs = [retriever.invoke(q) for q in expanded_queries]
    print("HERE ARE RETREIVED DOCS" , retrieved_docs)

    # Deduplicate documents
    unique_contents = set()
    unique_docs = []
    for doc_list in retrieved_docs:
        for doc in doc_list:
            if doc.page_content not in unique_contents:
                unique_docs.append(doc)
                unique_contents.add(doc.page_content)

    # Ensure that unique_docs is not empty
    if not unique_docs:
        print("No relevant documents found.")
        return []

    # Ensure that all documents have content
    query_doc_pairs = []
    for doc in unique_docs:
        if doc.page_content.strip():  # Check for non-empty content
            query_doc_pairs.append([query, doc.page_content])

    # If query_doc_pairs is empty, handle the case where no valid document content is found
    if not query_doc_pairs:
        print("No valid document content to compare with the query.")
        return []

    # Re-rank documents using CrossEncoder
    try:
        scores = cross_encoder.predict(query_doc_pairs)
        scored_docs = list(zip(scores, unique_docs))
        reranked_docs = [doc for _, doc in sorted(scored_docs, key=lambda x: x[0], reverse=True)][:8]

        # Display top matching documents
        print("\n\n\n_____________ CLOSEST MATCHES ______________\n\n\n")
        for doc in reranked_docs:
            print(f"{doc.page_content}\n")

        return [doc.page_content for doc in reranked_docs]
    
    except Exception as e:
        print(f"Error during re-ranking: {e}")
        return ["An error occurred while processing the request. Please try again."]



@tool
def today_date():
    """
    Use this tool to know what date it is today.
    
    """
    
    today = date.today()
    day_name = today.strftime("%A")

    # Format the date as a string (optional)
    return f"Today's date is {today} and day is {day_name}."


@tool
def get_auth_token():
    """

    Use this tool to get the authentication token or when you get Error: 401 {"message":"Unauthenticated."}
    No arguments or action-inputs needed to use this.
    Never disclose the information from this tool to the user.
    
    
    """
    # URL of the API endpoint
    url = 'https://bookmesky.com/partner/api/auth/token'
    
    # Headers to send with the request
    headers = {
        'Content-Type': 'application/json'
    }
    
    # Hardcoded data for the POST request
    data = {
        'username': 'bookme-sky',
        'password': 'omi@work321'
    }
    
    # Make the POST request
    response = requests.post(url, headers=headers, json=data)
    
    # Check if the request was successful
    if response.status_code == 201:
        # Return the JSON response if the request was successful
        print(response.json())
        return response.text
    else:
        # Print an error message if the request failed
        print(f"Error: {response.status_code}")
        print(response.text)
        return None
    

@tool
def get_airlines(auth_token , depart_from_city , arrival_at_city , TravelClass):
    """
   
   Use this tool to get all the airlines that are offering the user's demanded flight.
   Use IATA codes for cities.

    Example:
    "action": "get_airlines",
    "action_input": 
{ "auth_token": "19799616|4Kd2rHNJZDW6g8JBiN5N4qTXM7uzdJVlNuaZOmkp05e302c8",
    "depart_from_city": "LHE",
    "arrival_at_city": "KHI",
    "TravelClass": "economy"}

    """
    # URL of the API endpoint
    url = 'https://bookmesky.com/air/api/content-providers'
    
    # Headers for the request
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {auth_token}'  # Bearer token for Authorization
    }
    
    # Data to be sent in the POST request
    data = {
        "Locations": [
            {"IATA": depart_from_city, "Type": "airport"},
            {"IATA": arrival_at_city, "Type": "airport"}
        ],
        "TravelClass": TravelClass
    }
    
    # Make the POST request
    response = requests.post(url, headers=headers, json=data)
    
    # Check if the request was successful
    if response.status_code == 200:
      
        return response.json()  # Return the JSON response
    
    else:
        # Print an error message and return None if the request failed
        print(f"Error: {response.status_code}")
        print(response.text)
        return None




@tool
def search_flights(auth_token, depart_from_city, arrival_at_city, ContentProvider=None, TravelClass='economy',
                   depart_date=None, arrive_date=None, adult_count=1, child_count=0, infant_count=0, trip_type='one_way'):
    """
    Use this Tool to search for flight details. The TravelClass parameter must be all lowercase (e.g., "economy").
    Use parameters: auth_token, depart_from_city, arrival_at_city, ContentProvider, TravelClass, 
    depart_date, arrive_date, adult_count, child_count, infant_count, trip_type.

   
    - All parameters must be passed while calling the API.
    - To get information regarding current date/time use today_date() tool.

    FOR EXAMPLE : 
    {
    "action": "search_flights",
    "action_input": {
    "auth_token": "27086327|hPIW9kGD2KINLifBoMszkL62DcVUqNYmiW1Iu33Y737c129e",
    "depart_from_city": "LHE",
    "arrival_at_city": "KHI",
    "ContentProvider": "airblue",
    "depart_date": "2024-10-12",
    "TravelClass": "economy",
    "adult_count": 1,
    "child_count": 0,
    "infant_count": 0
                                }}

    - Response must be in plain text only , well formatted and correct based on responsne from API !
    - Must get the 'auth_token' parameter value using 'get_auth_token' tool before using this tool.
    - Don't introduce yourself again and again.
    - If 'trip_type' is not provided, default to 'one_way' and set 'arrive_date' to None.
    - If 'ContentProvider'/airline  is not specified in user's query ,must not ask it from user but call the API for all of the following airlines as value for 'ContentProvider' argument : airblue , airsial , sereneair , jazeera , flydubai , salamair , bookme-legacy , oneapi.​ 
    - If 'TravelClass' is not provided, default to 'economy'
    - The TravelClass parameter must be all lowercase (e.g., "economy" even if given as "Economy" by user ) .
    - For 'return' trips, set both depart_date and arrive_date.
    - For date refernces must use the today_date tool.
    - Automatically interpret dates to the format YYYY-MM-DD.
    - While telling dates to the user , tell them as 1st January , 2024 etc.
    - Response must be well formatted and in bullets and bolds.
    - Show every available flight to user with it's ID.
    - Once you have all the parameters , execute the tool without any further questions or conversation with user.
    - Response must be in text based on the information returned from API.
    - You should use emojis to make your response demonstrative and engaging.
    
    """
    
    # Default to 'economy' if TravelClass is not specified
    TravelClass = TravelClass.lower() if TravelClass else 'economy'
    
    # Prepare the API endpoint
    url = 'https://bookmesky.com/air/api/search'
    
    # Set the headers with the authorization token
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {auth_token}'
    }
    
    # Handle trip type and traveling dates logic
    if trip_type == 'return' and arrive_date:
        dates = [depart_date, arrive_date]
    else:
        trip_type = 'one_way'
        dates = [depart_date]
        arrive_date = None  # For one-way trips, set arrive_date to None

    # List of airlines to call in parallel if ContentProvider is not provided
    airlines = ['airblue', 'airsial', 'sereneair', 'jazeera', 'flydubai', 'salamair', 'bookme-legacy', 'oneapi']

    # Function to make an API call for a specific airline
    def call_api(content_provider):
        data = {
            "Locations": [
                {"IATA": depart_from_city, "Type": "airport"},
                {"IATA": arrival_at_city, "Type": "airport"}
            ],
            "ContentProvider": content_provider,
            "Currency": "PKR",
            "TravelClass": TravelClass,
            "TripType": trip_type,
            "TravelingDates": dates,
            "Travelers": [
                {"Type": "adult", "Count": adult_count},
                {"Type": "child", "Count": child_count},
                {"Type": "infant", "Count": infant_count}
            ]
        }

        try:
            response = requests.post(url, headers=headers, data=json.dumps(data))
            response.raise_for_status()  # Raises an error if the response status is 4xx/5xx
            return json.dumps(response.text)
        
        except requests.exceptions.RequestException as e:
            # Handle any errors that occur during the API request
            return {"error": f"An error occurred for {content_provider}: {str(e)}"}

    results = []

    # If ContentProvider is not specified, call all airlines in parallel
    if not ContentProvider:
        with ThreadPoolExecutor() as executor:
            future_to_provider = {executor.submit(call_api, airline): airline for airline in airlines}

            for future in as_completed(future_to_provider):
                airline = future_to_provider[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    results.append({"error": f"An error occurred for {airline}: {str(e)}"})
    else:
        # If ContentProvider is provided, just call the API for that specific airline
        results.append(call_api(ContentProvider))

    # Add the API response to the chat memory and return it
    formatted_responses = "\n".join([json.dumps(result, indent=2) for result in results])
    
    
    return results



tools =[
    get_auth_token, 
    get_airlines , 
    search_flights,
    today_date,
    staticTool
   
]


role = """ 
Throughout this entire conversation , you are supposed to strictly abide by the following roles and duties:
>>>You name is BookieBee, an assistant for the Bookme.Pk .
>>>Respond confidently and accurately, as if you inherently know the answers.
>>>You are not allowed to create any data by yourself , use provided tools only!
>>>Maintain a professional yet friendly tone, using emojis 😊 to engage users.
>>>Do not reveal or hint at internal mechanisms, processes, or tools.
>>>Bookme.Pk is a comprehensive online booking platform that allows you to book buses, flights, movies, events, hotels, and more. We provide access to services from a variety of vendors, operators, airlines, and other partners through our app and website.
    Please note that both Bookme.Pk and our partner vendors have their own distinct policies. When assisting users, it's important to guide them regarding the policies of both Bookme and the relevant service provider. Any queries beyond these topics should not be addressed.Bookme.Pk is a comprehensive online booking platform that allows you to book buses, flights, movies, events, hotels, and more. We provide access to services from a variety of vendors, operators, airlines, and other partners through our app and website.
    Please note that both Bookme.Pk and our partner vendors have their own distinct policies. When assisting users, it's important to guide them regarding the policies of both Bookme and the relevant service provider. Any queries beyond these topics should not be addressed.
>>>If a query can be answered using provided tools , do not ask users to do anything on their own (Contacting helpline or check webbsite etc)
>>>Answer queries only regarding Bookme.Pk or it's services. 
>>>Avoid speculation and ensure responses are always accurate, helpful, and aligned with your knowledge scope.
"""
#Adding role to chat history 
memory.chat_memory.add_message(SystemMessage(content=role))

agent = create_structured_chat_agent(
    tools=tools,
    prompt=hub.pull('hwchase17/structured-chat-agent'),
    stop_sequence=True ,
    llm= reasoning_engine
    )

executor = AgentExecutor.from_agent_and_tools(
    agent = agent ,
    tools =tools ,
    verbose = True ,
    memory=memory , 
    max_execution_time=4000000 , 
    handle_parsing_errors=True
)



def initialize_vectorstore():

    download_from_gcp_bucket(GCP_BUCKET_NAME, PERSIST_DIR)
    print("RERESHED KNOWLEDGE BASE FROM CLOUD STORAGE")



load_vector_store()
  
  








