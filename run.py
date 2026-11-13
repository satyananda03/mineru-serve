import uvicorn
PORT = 8000

def main() -> None:
    uvicorn.run("src.api.main:app", host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()