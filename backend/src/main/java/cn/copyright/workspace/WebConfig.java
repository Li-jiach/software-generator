package cn.copyright.workspace;

import jakarta.servlet.http.*;
import java.net.URI;
import java.util.Set;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.*;
import org.springframework.web.servlet.HandlerInterceptor;

@Configuration
class WebConfig implements WebMvcConfigurer {
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(new HandlerInterceptor() {
            public boolean preHandle(HttpServletRequest req,HttpServletResponse res,Object handler) {
                res.setHeader("X-Content-Type-Options","nosniff");
                res.setHeader("Cache-Control","no-store");
                if (!Set.of("GET","HEAD","OPTIONS").contains(req.getMethod())) {
                    String origin=req.getHeader("Origin");
                    if (origin!=null) {
                        try {
                            URI uri=URI.create(origin);
                            String host=uri.getHost();
                            boolean same=origin.equals(req.getScheme()+"://"+req.getHeader("Host"));
                            boolean local=Set.of("localhost","127.0.0.1").contains(req.getServerName()) && Set.of("localhost","127.0.0.1").contains(host) && uri.getPort()==5173;
                            if (!same&&!local) throw new ApiException(403,"拒绝跨站请求");
                        } catch (IllegalArgumentException e) { throw new ApiException(403,"请求来源不合法"); }
                    }
                }
                return true;
            }
        }).addPathPatterns("/api/**");
    }
    public void addResourceHandlers(ResourceHandlerRegistry registry) {
        registry.addResourceHandler("/**").addResourceLocations("classpath:/static/");
    }
}
