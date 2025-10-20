#import packages
import os
import pandas as pd
import re
import plotly.express as px
import time
from dotenv import load_dotenv
from google import genai
from google.genai import types # Import the types module
import streamlit as st

# import openai

#load environment variables from .env file
load_dotenv()

# Google Gemini implementation
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Helper function to get dataset path with multiple fallback options
def get_dataset_path():
    """Try multiple possible locations for the CSV file"""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # List of possible paths to try (in order of preference)
    possible_paths = [
        os.path.join(current_dir, "data", "customer_reviews.csv"),           # Original: data subfolder
        os.path.join(current_dir, "customer_reviews.csv"),                   # Same directory as app
        os.path.join(current_dir, "..", "data", "customer_reviews.csv"),     # Parent directory's data folder
        os.path.join(current_dir, "..", "customer_reviews.csv"),             # Parent directory
        os.path.join(current_dir, "..", "..", "customer_reviews.csv"),       # Two levels up
    ]
    
    # Try each path and return the first one that exists
    for i, path in enumerate(possible_paths):
        if os.path.exists(path):
            return path
    
    # If none found, return the original path (will show helpful error message)
    return possible_paths[0]

# Cached function to load dataset
@st.cache_data
def load_dataset(csv_path):
    """Load and cache the dataset to avoid repeated file reads"""
    return pd.read_csv(csv_path)


st.title("Playing with GenAI")
st.write("This app keep response simple using GenAI.")

# Helper function to clean text
def clean_text(text):
    text = text.lower().strip()
    text = re.sub(r'[^\w\s]', '', text)
    return text

# Helper function to convert score to sentiment label
def score_to_sentiment(score):
    """Convert numeric sentiment score to descriptive text"""
    if score <= -0.6:
        return "Bad"
    elif score <= -0.2:
        return "Negative" 
    elif score <= 0.2:
        return "Neutral"
    elif score <= 0.6:
        return "Positive"
    else:
        return "Excellent"

# Helper function to get sentiment score using GenAI with rate limiting
def get_sentiment(text):
    # cleaned = clean_text(text)
    cleaned = text
    if not cleaned or cleaned.isspace():
        return "Neutral"  # Neutral sentiment for empty or whitespace-only reviews
    try:
        prompt = f"Please provide a sentiment score between -1 (very negative) to 1 (very positive) for the following review summary: '{cleaned}'. Only return the numeric score."
        response = client.models.generate_content(
                model="gemini-2.0-flash-exp",
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction="You are a sentiment analysis assistant. Provide only the numeric sentiment score.",
                    temperature=0.0,
                    max_output_tokens=10
                )
        )
        score = float(response.text.strip())
        # Convert numeric score to descriptive sentiment
        sentiment_label = score_to_sentiment(score)
        return sentiment_label
    except Exception as e:
        st.error(f"API error: {e}")
        return "Neutral"  # Default to neutral if parsing fails

# Human-controlled batch processing with manual continuation
def process_single_batch(df, start_idx, batch_size=5):
    """
    Process a single small batch and return results
    batch_size: Keep very small (5) to stay well under rate limits
    """
    end_idx = min(start_idx + batch_size, len(df))
    batch_df = df.iloc[start_idx:end_idx]
    
    sentiments = []
    for idx, row in batch_df.iterrows():
        sentiment = get_sentiment(row['SUMMARY'])
        sentiments.append((idx, sentiment))
        # Conservative delay between each request
        time.sleep(8)  # 8 seconds = 7.5 RPM (well under 10 RPM)
    
    return sentiments, end_idx

# Initialize session state for batch processing
def initialize_batch_state(df):
    """Initialize or reset the batch processing state"""
    st.session_state["batch_start_idx"] = 0
    st.session_state["processed_sentiments"] = {}
    st.session_state["processing_active"] = False
    st.session_state["total_rows"] = len(df)

# Smart continuation: find the next unprocessed position
def get_next_batch_start(processed_sentiments, total_rows):
    """Find the next position that hasn't been processed yet"""
    if not processed_sentiments:
        return 0
    
    # Find the first unprocessed position
    for i in range(total_rows):
        if i not in processed_sentiments:
            return i
    
    return total_rows  # All processed

col1, col2 = st.columns(2)

with col1:
    if st.button("📥 Ingest Dataset"):
        try:
            csv_path = get_dataset_path()
            
            if os.path.exists(csv_path):
                # Use cached dataset loading
                st.session_state["df"] = load_dataset(csv_path)
                st.success(f"Dataset loaded successfully! 🎯 (Found at: {csv_path})")
            else:
                # Show all attempted paths for debugging
                current_dir = os.path.dirname(os.path.abspath(__file__))
                attempted_paths = [
                    os.path.join(current_dir, "data", "customer_reviews.csv"),
                    os.path.join(current_dir, "customer_reviews.csv"),
                    os.path.join(current_dir, "..", "data", "customer_reviews.csv"),
                    os.path.join(current_dir, "..", "customer_reviews.csv"),
                    os.path.join(current_dir, "..", "..", "customer_reviews.csv"),
                ]
                
                st.error("📂 **CSV file not found!** Tried these locations:")
                for i, path in enumerate(attempted_paths, 1):
                    exists = "✅" if os.path.exists(path) else "❌"
                    st.write(f"{exists} {i}. `{path}`")
                
                st.info("💡 **Solution:** Place your `customer_reviews.csv` file in any of the above locations.")
                
        except Exception as e:
            st.error(f"Error loading dataset: {str(e)}")

with col2:
    # Initialize batch processing if not exists
    if "df" in st.session_state and "batch_start_idx" not in st.session_state:
        initialize_batch_state(st.session_state["df"])
    
    if "df" in st.session_state:
        total_rows = st.session_state["total_rows"]
        processed_sentiments = st.session_state.get("processed_sentiments", {})
        processed_count = len(processed_sentiments)
        
        # Smart continuation: find next unprocessed position
        current_idx = get_next_batch_start(processed_sentiments, total_rows)
        st.session_state["batch_start_idx"] = current_idx  # Update to ensure consistency
        
        # Show progress info
        st.write(f"📊 **Sentiment Analysis Progress:** {processed_count}/{total_rows} completed")
        
        # Show continuation status
        if processed_count > 0:
            st.info(f"🔄 **Resuming from:** Row {current_idx + 1} (You can continue where you left off)")
        
        if processed_count < total_rows:
            # Show what will happen next
            remaining = min(5, total_rows - current_idx)
            st.write(f"🎯 **Next batch:** Process {remaining} reviews (positions {current_idx+1}-{current_idx+remaining})")
            st.write(f"⏱️ **Time per batch:** ~45 seconds (8 sec/review × 5 reviews + buffer)")
            
            # Show which reviews are already processed
            if processed_count > 0:
                processed_positions = sorted(st.session_state["processed_sentiments"].keys())
                if len(processed_positions) <= 10:
                    st.write(f"✅ **Already processed positions:** {[pos+1 for pos in processed_positions]}")
                else:
                    st.write(f"✅ **Already processed:** {len(processed_positions)} reviews (positions 1-{max(processed_positions)+1})")
            
            col2a, col2b, col2c = st.columns(3)
            
            with col2a:
                if st.button("▶️ Process Next 5"):
                    try:
                        with st.spinner(f"Processing reviews {current_idx+1} to {current_idx+remaining}..."):
                            batch_results, new_idx = process_single_batch(
                                st.session_state["df"], 
                                current_idx, 
                                batch_size=5
                            )
                            
                            # Store results
                            for idx, sentiment in batch_results:
                                st.session_state["processed_sentiments"][idx] = sentiment
                            
                            # Update the start index for next batch
                            st.session_state["batch_start_idx"] = new_idx
                            
                            # Show detailed success message
                            processed_positions = [idx+1 for idx, _ in batch_results]
                            st.success(f"✅ Processed {len(batch_results)} reviews at positions {processed_positions}!")
                            st.info(f"📈 **Total progress:** {len(st.session_state['processed_sentiments'])}/{total_rows} completed")
                            
                            if new_idx < total_rows:
                                st.info(f"🔄 **Next batch will start from position:** {new_idx + 1}")
                            
                    except Exception as e:
                        st.error(f"❌ Error processing batch: {str(e)}")
            
            with col2b:
                if st.button("⏹️ Stop & Apply"):
                    if st.session_state["processed_sentiments"]:
                        # Apply processed sentiments to dataframe with proper labels
                        sentiment_labels = ["Not Analysed Yet"] * len(st.session_state["df"])
                        for idx, sentiment in st.session_state["processed_sentiments"].items():
                            sentiment_labels[idx] = sentiment
                        
                        st.session_state["df"]["SENTIMENT_LABEL"] = sentiment_labels
                        processed_count = len(st.session_state["processed_sentiments"])
                        remaining_count = len(st.session_state["df"]) - processed_count
                        st.success(f"✅ Applied {processed_count} sentiment labels! {remaining_count} marked as 'Not Analysed Yet'")
                    else:
                        st.warning("No sentiments processed yet.")
            
            with col2c:
                if st.button("🔄 Reset"):
                    initialize_batch_state(st.session_state["df"])
                    st.success("🔄 Reset processing state!")
        
        else:
            # All processing complete
            st.success("🎉 **All sentiment analysis complete!**")
            if st.button("✅ Apply All Results"):
                # Apply all processed sentiments
                sentiment_labels = ["Not Analysed Yet"] * len(st.session_state["df"])
                for idx, sentiment in st.session_state["processed_sentiments"].items():
                    sentiment_labels[idx] = sentiment
                
                st.session_state["df"]["SENTIMENT_LABEL"] = sentiment_labels
                st.success("✅ All sentiment labels applied to dataset!")
    
    else:
        st.warning("Please ingest the dataset first.")

# Display the dataset if it exists
if "df" in st.session_state:
    # Product filter dropdown
    st.subheader("🔍 Filter by Product")
    product = st.selectbox("Choose a product", ["All Products"] + list(st.session_state["df"]["PRODUCT"].unique()))
    st.subheader(f"📁 Reviews for {product}")

    if product != "All Products":
        filtered_df = st.session_state["df"][st.session_state["df"]["PRODUCT"] == product]
    else:
        filtered_df = st.session_state["df"]
    st.dataframe(filtered_df)

    # show statistics
    if "SENTIMENT_LABEL" in st.session_state["df"].columns:
        st.subheader("📊 Sentiment Distribution by Product")
        
        # Create a count of sentiment labels by product
        sentiment_counts = st.session_state["df"].groupby(["PRODUCT", "SENTIMENT_LABEL"]).size().reset_index(name='Count')
        
        # Create a bar chart using plotly
        if not sentiment_counts.empty:
            fig = px.bar(sentiment_counts, 
                        x="PRODUCT", 
                        y="Count", 
                        color="SENTIMENT_LABEL",
                        title="Sentiment Distribution Across Products",
                        color_discrete_map={
                            "Bad": "#d32f2f",
                            "Negative": "#f57c00", 
                            "Neutral": "#9e9e9e",
                            "Positive": "#388e3c",
                            "Excellent": "#1976d2",
                            "Not Analysed Yet": "#bdbdbd"  # Light gray for unprocessed
                        })
            st.plotly_chart(fig)
        
        # Show summary table
        st.subheader("📋 Sentiment Summary")
        summary_table = st.session_state["df"]["SENTIMENT_LABEL"].value_counts()
        
        # Calculate analysis progress
        total_reviews = len(st.session_state["df"])
        not_analysed = summary_table.get("Not Analysed Yet", 0)
        analysed = total_reviews - not_analysed
        progress_percentage = (analysed / total_reviews) * 100
        
        # Show progress info
        st.metric(
            label="Analysis Progress", 
            value=f"{analysed}/{total_reviews}", 
            delta=f"{progress_percentage:.1f}% Complete"
        )
        
        # Show the summary table
        st.write(summary_table)