# Use a pre-built image that contains both Node.js and Python
FROM nikolaik/python-nodejs:python3.11-nodejs20

# Set the working directory
WORKDIR /app

# Copy the dependency definitions
COPY StockAnalyzer/requirements.txt ./StockAnalyzer/
COPY StockAnalyzerWeb/package.json ./StockAnalyzerWeb/

# Install Node dependencies
WORKDIR /app/StockAnalyzerWeb
RUN npm install

# Install Python dependencies
WORKDIR /app/StockAnalyzer
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the project files
WORKDIR /app
COPY . .

# Set Environment Variables
# This ensures that our server.js uses the system python (installed in the container)
ENV PYTHON_PATH=python
ENV STOCK_ANALYZER_DIR=/app/StockAnalyzer

# Set the Railway port
ENV PORT=3000
EXPOSE 3000

# Start the Node.js server
WORKDIR /app/StockAnalyzerWeb
CMD ["npm", "start"]
