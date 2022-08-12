# Local-Cached-DNS-Server

# Background  
DNS resolving is a critical process in web requesting. There are multiple public DNS servers including Google DNS, Level3 DNS, Open DNS and etc., and naturally there is always lookup latency to resolve the correct IP. Due to the location, the distance, the network status and the requested address, the latency can sometimes become so remarkable that it brings bad user experience. What's more, some domain name can be resolved to multiple IP addresses, and the communication delay between localhost and remote server is different. In this project, it always finds and stores the fastest IP. 

This project aims to provide a local DNS service with cache and persistence on Redis, furthermore, it detects the lookup latency between localhost and DNS server as well as the communication delay between localhost and target server, and keeps refining and storing the target IP that works the best. Next time you ask for the same domain name, the cache should be hit to save time.  

# Main Technique  
Python3, Redis, Knowledge about DNS and latency detection  

# Claim  
This is a POC for fun, enjoy! :)
