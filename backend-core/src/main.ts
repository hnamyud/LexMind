import { NestFactory, Reflector } from '@nestjs/core';
import { AppModule } from './app.module';
import { ConfigService } from '@nestjs/config';
import helmet from 'helmet';
import cookieParser from 'cookie-parser';
import { helmetConfig } from './config/helmet.config';
import { JwtAuthGuard } from './common/guards/jwt-auth.guard';
import { ValidationPipe, VersioningType } from '@nestjs/common';
import { TransformInterceptor } from './core/interceptors/transform.interceptor';
import { DocumentBuilder, SwaggerModule } from '@nestjs/swagger';
import { PoliciesGuard } from './common/guards/policy.guard';
import { CaslAbilityFactory } from './core/casl/ability.factory';

async function bootstrap() {
  const app = await NestFactory.create(AppModule);
  const configService = app.get(ConfigService);
  const reflector = app.get(Reflector);

  // Apply helmet middleware with custom config
  app.use(helmet(helmetConfig));

  // Config cookie (Http-only, Secure)
  app.use(cookieParser());

  // Config CORS
  app.enableCors({
    origin: configService.get<string>('FE_DOMAIN'), // FE domain
    methods: 'GET,HEAD,PUT,PATCH,POST,DELETE',
    credentials: true,
    allowedHeaders: [
      'Content-Type',
      'Authorization',
    ],
  });

  // Use JWT global
  app.useGlobalGuards(
    new JwtAuthGuard(reflector),
    new PoliciesGuard(reflector, app.get(CaslAbilityFactory)),
  );
  app.useGlobalPipes(new ValidationPipe(
    {
      whitelist: true, // Tự động bỏ các field không có trong DTO
      forbidNonWhitelisted: true, // (Tùy chọn) Báo lỗi luôn nếu gửi field lạ
      transform: true
    }
  ));

  // Transform response from controller
  app.useGlobalInterceptors(new TransformInterceptor(reflector));

  //Config versoning
  app.setGlobalPrefix('api');
  app.enableVersioning({
    type: VersioningType.URI,
    defaultVersion: '1',
  });

  // Swagger setup
  const swaggerConfig = new DocumentBuilder()
    .setTitle('Chatbot Law API')
    .setDescription(`
      ## API Documentation for Chatbot Law System
      ### 🔐 Authentication
      - Most endpoints require JWT Bearer token
      - Get token from \`/auth/login\` endpoint
      - Use "Authorize" button below to set token globally
      
      ### 📱 API Versioning
      - All endpoints are prefixed with \`/api/v1/\`
      - Default version: v1
      `)
    .setVersion('1.0')
    .addServer('http://localhost:8080', 'Development Server')
    .addBearerAuth(
      {
        type: 'http',
        scheme: 'bearer',
        bearerFormat: 'JWT',
        name: 'JWT',
        description: 'Enter JWT token (without Bearer prefix)',
        in: 'header'
      },
      'access-token',
    )
    .build();

  const document = SwaggerModule.createDocument(app, swaggerConfig);
  // Setup Swagger UI with options
  SwaggerModule.setup('docs', app, document, {
    swaggerOptions: {
      persistAuthorization: true, // Remember JWT token
      tagsSorter: 'alpha',        // Sort tags alphabetically
      operationsSorter: 'alpha',  // Sort operations alphabetically  
      docExpansion: 'none',       // Collapse all sections initially
      filter: true,               // Enable search filter
      showRequestHeaders: true,   // Show request headers
    },
    customSiteTitle: 'Chatbot Law API Docs', // Custom title
    customfavIcon: '/favicon.ico',               // Custom favicon
  });

  const port = configService.get('PORT')
  await app.listen(port);
}
bootstrap();
