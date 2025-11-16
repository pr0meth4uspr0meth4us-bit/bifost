from bifrost import create_app
from config import Config  # <-- ADD THIS IMPORT

# Pass the Config class directly into the factory
app = create_app(Config)

if __name__ == '__main__':
    app.run(debug=True)