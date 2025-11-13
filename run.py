from bifrost import create_app

app = create_app()

if __name__ == '__main__':
    # Setting debug=True enables auto-reload
    app.run(debug=True)