# Local-Cached-DNS-Server

# Backgroud  
DNS resolving is a critical process in web requesting. There are multiple public DNS servers, and naturally there is always latency to fetch the correct IP. Due to location, distance, network status and requested address, the latency can sometimes become so remarkable that brings bad user experience. This project aims to provide local DNS service with cache and persistence on Redis, furthermore, it detects the latency between localhost and DNS server as well as between localhost and destination server and keeps refining and storing the target IP that works the best. Next time you ask for the same address, the cache should be hit to save time.  

# Main Technique  
Python3, Redis, Knowledge about DNS and latency detection  

# This is a POC.
